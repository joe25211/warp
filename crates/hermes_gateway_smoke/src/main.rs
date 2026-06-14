use std::time::Duration;

use anyhow::{bail, Context, Result};
use futures_util::{Sink, SinkExt, Stream, StreamExt};
use session_sharing_protocol::common::{
    ActivePrompt, FeatureSupport, InputReplicaId, OrderedTerminalEvent, OrderedTerminalEventType,
    ParticipantId, Scrollback, Selection, UserID, WindowSize, WriteToPtyFailureReason,
    WriteToPtyRequestId, WriteToPtySeqNo,
};
use session_sharing_protocol::{sharer, viewer};
use websocket::{Message, WebSocket, WebsocketMessage};

const READ_TIMEOUT: Duration = Duration::from_secs(3);

#[tokio::main]
async fn main() -> Result<()> {
    let base_url = std::env::args()
        .nth(1)
        .or_else(|| std::env::var("WARP_SESSION_SHARING_SERVER_URL").ok())
        .context("usage: hermes_gateway_smoke <ws://host:port>")?;

    run(&base_url).await?;
    println!("rust viewer compat smoke ok");
    Ok(())
}

async fn run(base_url: &str) -> Result<()> {
    let base_url = base_url.trim_end_matches('/');
    let sharer_socket = WebSocket::connect_with_headers(
        &format!("{base_url}/sessions/create"),
        None::<&str>,
        Vec::new(),
    )
    .await
    .context("connect sharer websocket")?;
    let (mut sharer_sink, mut sharer_stream) = sharer_socket.split().await;

    send_sharer(&mut sharer_sink, sharer_initialize_message()).await?;
    let session_id = match read_sharer(&mut sharer_stream, "session initialized").await? {
        sharer::DownstreamMessage::SessionInitialized { session_id, .. } => session_id,
        other => bail!(
            "expected SessionInitialized, got {}",
            sharer_variant(&other)
        ),
    };

    send_sharer(
        &mut sharer_sink,
        sharer::UpstreamMessage::OrderedTerminalEvent(ordered_terminal_event(11, b"before")),
    )
    .await?;
    expect_sharer_ack(&mut sharer_stream, 11, "pre-join event ack").await?;

    let viewer_socket = WebSocket::connect_with_headers(
        &format!("{base_url}/sessions/join/{session_id}"),
        None::<&str>,
        Vec::new(),
    )
    .await
    .context("connect viewer websocket")?;
    let (mut viewer_sink, mut viewer_stream) = viewer_socket.split().await;

    send_viewer(&mut viewer_sink, viewer_initialize_message(None, None)).await?;
    let viewer_id = match read_viewer(&mut viewer_stream, "viewer join").await? {
        viewer::DownstreamMessage::JoinedSuccessfully {
            scrollback,
            active_prompt,
            latest_event_no,
            window_size,
            participant_list,
            viewer_id,
            viewer_firebase_uid,
            init_block_id,
            input_replica_id,
            detailed_source_type,
            source_task_id,
            ..
        } => {
            if !scrollback.blocks.is_empty() || scrollback.is_alt_screen_active {
                bail!("expected bounded empty scrollback from v0 gateway");
            }
            if active_prompt != ActivePrompt::WarpPrompt("fish>".to_owned()) {
                bail!("viewer active_prompt did not preserve sharer metadata");
            }
            if latest_event_no.is_some() {
                bail!("v0 gateway must not advertise replay latest_event_no");
            }
            if window_size.num_rows != 33 || window_size.num_cols != 120 {
                bail!("viewer window_size did not preserve sharer metadata");
            }
            if participant_list.present_viewers.is_empty() {
                bail!("viewer participant_list did not include the joined viewer");
            }
            if !viewer_firebase_uid.starts_with("local-viewer-") {
                bail!("viewer firebase uid mismatch: {viewer_firebase_uid}");
            }
            if init_block_id.to_string() != "block-rust-compat" {
                bail!("init_block_id mismatch: {init_block_id}");
            }
            if input_replica_id.to_string() != "input-rust-sharer" {
                bail!("input_replica_id mismatch: {input_replica_id}");
            }
            match detailed_source_type {
                sharer::SessionSourceType::AmbientAgent { task_id } => {
                    if task_id.as_deref() != Some("task-rust-compat") {
                        bail!("detailed_source_type task_id mismatch: {task_id:?}");
                    }
                }
                sharer::SessionSourceType::User => {
                    bail!("expected AmbientAgent detailed_source_type")
                }
            }
            if source_task_id.as_deref() != Some("task-rust-compat") {
                bail!("source_task_id mismatch: {source_task_id:?}");
            }
            viewer_id
        }
        other => bail!(
            "expected JoinedSuccessfully, got {}",
            viewer_variant(&other)
        ),
    };

    send_sharer(
        &mut sharer_sink,
        sharer::UpstreamMessage::OrderedTerminalEvent(ordered_terminal_event(12, b"live")),
    )
    .await?;
    expect_sharer_ack(&mut sharer_stream, 12, "live event ack").await?;
    match read_viewer(&mut viewer_stream, "viewer live event").await? {
        viewer::DownstreamMessage::OrderedTerminalEvent(event) => {
            if event.event_no != 0 {
                bail!("expected viewer-local event_no 0, got {}", event.event_no);
            }
            expect_pty_bytes(&event, b"live")?;
        }
        other => bail!(
            "expected OrderedTerminalEvent, got {}",
            viewer_variant(&other)
        ),
    }

    send_viewer(
        &mut viewer_sink,
        viewer::UpstreamMessage::WriteToPty {
            request_id: WriteToPtyRequestId {
                participant_id: viewer_id.clone(),
                op_no: WriteToPtySeqNo::zero(),
            },
            bytes: b"x".to_vec(),
        },
    )
    .await?;
    match read_viewer(&mut viewer_stream, "viewer write rejection").await? {
        viewer::DownstreamMessage::WriteToPtyRequestFailed { reason } => match reason {
            WriteToPtyFailureReason::InsufficientPermissions => {}
            other => bail!("expected InsufficientPermissions, got {other:?}"),
        },
        other => bail!(
            "expected WriteToPtyRequestFailed, got {}",
            viewer_variant(&other)
        ),
    }

    let rejoin_socket = WebSocket::connect_with_headers(
        &format!("{base_url}/sessions/join/{session_id}"),
        None::<&str>,
        Vec::new(),
    )
    .await
    .context("connect rejoin viewer websocket")?;
    let (mut rejoin_sink, mut rejoin_stream) = rejoin_socket.split().await;
    send_viewer(
        &mut rejoin_sink,
        viewer_initialize_message(Some(viewer_id), Some(0)),
    )
    .await?;
    match read_viewer(&mut rejoin_stream, "viewer rejoin").await? {
        viewer::DownstreamMessage::RejoinedSuccessfully { participant_list } => {
            if participant_list.present_viewers.is_empty() {
                bail!("rejoin participant_list lost viewer presence");
            }
        }
        other => bail!(
            "expected RejoinedSuccessfully, got {}",
            viewer_variant(&other)
        ),
    }

    send_sharer(
        &mut sharer_sink,
        sharer::UpstreamMessage::EndSession {
            reason: sharer::SessionEndedReason::EndedBySharer,
        },
    )
    .await?;
    match read_viewer(&mut rejoin_stream, "viewer SessionEnded").await? {
        viewer::DownstreamMessage::SessionEnded { reason } => match reason {
            viewer::SessionEndedReason::EndedBySharer => {}
            other => bail!("expected EndedBySharer, got {other:?}"),
        },
        other => bail!("expected SessionEnded, got {}", viewer_variant(&other)),
    }

    Ok(())
}

fn sharer_initialize_message() -> sharer::UpstreamMessage {
    sharer::UpstreamMessage::Initialize(sharer::InitPayload {
        scrollback: Scrollback {
            blocks: Vec::new(),
            is_alt_screen_active: false,
        },
        active_prompt: ActivePrompt::WarpPrompt("fish>".to_owned()),
        window_size: WindowSize {
            num_rows: 33,
            num_cols: 120,
        },
        user_id: UserID {
            anonymous_id: "rust-sharer-user".to_owned(),
            access_token: None,
        },
        selection: Selection::None,
        init_block_id: "block-rust-compat".to_owned().into(),
        input_replica_id: InputReplicaId::from("input-rust-sharer".to_owned()),
        telemetry_context: None,
        lifetime: sharer::Lifetime::Ephemeral,
        universal_developer_input_context: None,
        source_type: sharer::SessionSourceType::AmbientAgent {
            task_id: Some("task-rust-compat".to_owned()),
        },
        source_task_id: Some("task-rust-compat".to_owned()),
        feature_support: FeatureSupport {
            supports_agent_view: true,
            supports_full_role: true,
            supports_full_role_for_real: true,
        },
    })
}

fn viewer_initialize_message(
    viewer_id: Option<ParticipantId>,
    last_received_event_no: Option<usize>,
) -> viewer::UpstreamMessage {
    viewer::UpstreamMessage::Initialize(viewer::InitPayload {
        viewer_id,
        user_id: UserID {
            anonymous_id: "local-viewer-user".to_owned(),
            access_token: None,
        },
        last_received_event_no,
        latest_block_id: None,
        telemetry_context: None,
        feature_support: FeatureSupport {
            supports_agent_view: true,
            supports_full_role: true,
            supports_full_role_for_real: true,
        },
    })
}

fn ordered_terminal_event(event_no: usize, bytes: &[u8]) -> OrderedTerminalEvent {
    OrderedTerminalEvent {
        event_no,
        event_type: OrderedTerminalEventType::PtyBytesRead {
            bytes: bytes.to_vec(),
        },
    }
}

async fn send_sharer<S>(sink: &mut S, message: sharer::UpstreamMessage) -> Result<()>
where
    S: Sink<Message, Error = websocket::Error> + Unpin,
{
    sink.send(Message::new(message.to_json()?))
        .await
        .context("send sharer message")
}

async fn send_viewer<S>(sink: &mut S, message: viewer::UpstreamMessage) -> Result<()>
where
    S: Sink<Message, Error = websocket::Error> + Unpin,
{
    sink.send(Message::new(message.to_json()?))
        .await
        .context("send viewer message")
}

async fn read_sharer<S>(stream: &mut S, label: &str) -> Result<sharer::DownstreamMessage>
where
    S: Stream<Item = Result<Message, websocket::Error>> + Unpin,
{
    let text = read_text(stream, label).await?;
    sharer::DownstreamMessage::from_json(&text)
        .with_context(|| format!("parse sharer downstream {label}: {text}"))
}

async fn read_viewer<S>(stream: &mut S, label: &str) -> Result<viewer::DownstreamMessage>
where
    S: Stream<Item = Result<Message, websocket::Error>> + Unpin,
{
    let text = read_text(stream, label).await?;
    viewer::DownstreamMessage::from_json(&text)
        .with_context(|| format!("parse viewer downstream {label}: {text}"))
}

async fn read_text<S>(stream: &mut S, label: &str) -> Result<String>
where
    S: Stream<Item = Result<Message, websocket::Error>> + Unpin,
{
    let message = tokio::time::timeout(READ_TIMEOUT, stream.next())
        .await
        .with_context(|| format!("timed out waiting for {label}"))?
        .with_context(|| format!("websocket closed while waiting for {label}"))?
        .with_context(|| format!("websocket error while waiting for {label}"))?;
    message
        .text()
        .map(str::to_owned)
        .with_context(|| format!("expected text websocket frame for {label}"))
}

async fn expect_sharer_ack<S>(stream: &mut S, expected_event_no: usize, label: &str) -> Result<()>
where
    S: Stream<Item = Result<Message, websocket::Error>> + Unpin,
{
    match read_sharer(stream, label).await? {
        sharer::DownstreamMessage::EventsProcessedAck {
            latest_processed_event_no,
        } if latest_processed_event_no == expected_event_no => Ok(()),
        other => bail!(
            "expected EventsProcessedAck({expected_event_no}), got {}",
            sharer_variant(&other)
        ),
    }
}

fn expect_pty_bytes(event: &OrderedTerminalEvent, expected: &[u8]) -> Result<()> {
    match &event.event_type {
        OrderedTerminalEventType::PtyBytesRead { bytes } if bytes == expected => Ok(()),
        other => bail!("expected PtyBytesRead({expected:?}), got {other:?}"),
    }
}

fn sharer_variant(message: &sharer::DownstreamMessage) -> &'static str {
    match message {
        sharer::DownstreamMessage::SessionInitialized { .. } => "SessionInitialized",
        sharer::DownstreamMessage::FailedToInitializeSession { .. } => "FailedToInitializeSession",
        sharer::DownstreamMessage::SessionTerminated { .. } => "SessionTerminated",
        sharer::DownstreamMessage::SessionReconnected { .. } => "SessionReconnected",
        sharer::DownstreamMessage::FailedToReconnect { .. } => "FailedToReconnect",
        sharer::DownstreamMessage::EventsProcessedAck { .. } => "EventsProcessedAck",
        sharer::DownstreamMessage::ParticipantListUpdated(_) => "ParticipantListUpdated",
        sharer::DownstreamMessage::ParticipantPresenceUpdated(_) => "ParticipantPresenceUpdated",
        sharer::DownstreamMessage::RoleRequested { .. } => "RoleRequested",
        sharer::DownstreamMessage::RoleRequestCancelled { .. } => "RoleRequestCancelled",
        sharer::DownstreamMessage::ParticipantRoleChanged { .. } => "ParticipantRoleChanged",
        sharer::DownstreamMessage::ControlActionRequested { .. } => "ControlActionRequested",
        sharer::DownstreamMessage::InputUpdated(_) => "InputUpdated",
        sharer::DownstreamMessage::InputUpdateRejectedAck { .. } => "InputUpdateRejectedAck",
        sharer::DownstreamMessage::CommandExecutionRequested { .. } => "CommandExecutionRequested",
        sharer::DownstreamMessage::WriteToPtyRequested { .. } => "WriteToPtyRequested",
        sharer::DownstreamMessage::AgentPromptRequested { .. } => "AgentPromptRequested",
        sharer::DownstreamMessage::LinkAccessLevelUpdateResponse(_) => {
            "LinkAccessLevelUpdateResponse"
        }
        sharer::DownstreamMessage::AddGuestsResponse(_) => "AddGuestsResponse",
        sharer::DownstreamMessage::RemoveGuestResponse(_) => "RemoveGuestResponse",
        sharer::DownstreamMessage::UpdatePendingUserRoleResponse(_) => {
            "UpdatePendingUserRoleResponse"
        }
        sharer::DownstreamMessage::TeamAccessLevelUpdateResponse(_) => {
            "TeamAccessLevelUpdateResponse"
        }
        sharer::DownstreamMessage::UniversalDeveloperInputContextUpdated(_) => {
            "UniversalDeveloperInputContextUpdated"
        }
        sharer::DownstreamMessage::ViewerTerminalSizeReported { .. } => {
            "ViewerTerminalSizeReported"
        }
        sharer::DownstreamMessage::Pong { .. } => "Pong",
    }
}

fn viewer_variant(message: &viewer::DownstreamMessage) -> &'static str {
    match message {
        viewer::DownstreamMessage::JoinedSuccessfully { .. } => "JoinedSuccessfully",
        viewer::DownstreamMessage::RejoinedSuccessfully { .. } => "RejoinedSuccessfully",
        viewer::DownstreamMessage::FailedToJoin { .. } => "FailedToJoin",
        viewer::DownstreamMessage::SessionEnded { .. } => "SessionEnded",
        viewer::DownstreamMessage::ActivePromptUpdated(_) => "ActivePromptUpdated",
        viewer::DownstreamMessage::UniversalDeveloperInputContextUpdated(_) => {
            "UniversalDeveloperInputContextUpdated"
        }
        viewer::DownstreamMessage::OrderedTerminalEvent(_) => "OrderedTerminalEvent",
        viewer::DownstreamMessage::ParticipantListUpdated(_) => "ParticipantListUpdated",
        viewer::DownstreamMessage::ParticipantPresenceUpdated(_) => "ParticipantPresenceUpdated",
        viewer::DownstreamMessage::RoleRequestInFlight(_) => "RoleRequestInFlight",
        viewer::DownstreamMessage::RoleRequestResponse(_) => "RoleRequestResponse",
        viewer::DownstreamMessage::ParticipantRoleChanged { .. } => "ParticipantRoleChanged",
        viewer::DownstreamMessage::InputUpdated(_) => "InputUpdated",
        viewer::DownstreamMessage::InputUpdateRejected { .. } => "InputUpdateRejected",
        viewer::DownstreamMessage::CommandExecutionRequestInFlight(_) => {
            "CommandExecutionRequestInFlight"
        }
        viewer::DownstreamMessage::CommandExecutionRequestFailed { .. } => {
            "CommandExecutionRequestFailed"
        }
        viewer::DownstreamMessage::WriteToPtyRequestFailed { .. } => "WriteToPtyRequestFailed",
        viewer::DownstreamMessage::AgentPromptRequestInFlight(_) => "AgentPromptRequestInFlight",
        viewer::DownstreamMessage::AgentPromptRequestFailed { .. } => "AgentPromptRequestFailed",
        viewer::DownstreamMessage::ControlActionRequestFailed { .. } => {
            "ControlActionRequestFailed"
        }
        viewer::DownstreamMessage::ViewerRemoved { .. } => "ViewerRemoved",
        viewer::DownstreamMessage::LinkAccessLevelUpdateResponse(_) => {
            "LinkAccessLevelUpdateResponse"
        }
        viewer::DownstreamMessage::AddGuestsResponse(_) => "AddGuestsResponse",
        viewer::DownstreamMessage::RemoveGuestResponse(_) => "RemoveGuestResponse",
        viewer::DownstreamMessage::UpdatePendingUserRoleResponse(_) => {
            "UpdatePendingUserRoleResponse"
        }
        viewer::DownstreamMessage::TeamAccessLevelUpdateResponse(_) => {
            "TeamAccessLevelUpdateResponse"
        }
        viewer::DownstreamMessage::Pong { .. } => "Pong",
        #[allow(deprecated)]
        viewer::DownstreamMessage::LinkAccessLevelUpdated { .. } => "LinkAccessLevelUpdated",
        #[allow(deprecated)]
        viewer::DownstreamMessage::TeamAccessLevelUpdated { .. } => "TeamAccessLevelUpdated",
    }
}
