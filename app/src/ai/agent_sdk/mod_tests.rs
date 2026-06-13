use serde_json::json;
use warp_cli::agent::{
    AgentCommand, Harness, HiddenComputerUseArgs, PromptArg, RunAgentArgs, SnapshotArgs,
};
use warp_cli::artifact::{
    ArtifactCommand, DownloadArtifactArgs, GetArtifactArgs, UploadArtifactArgs,
};
use warp_cli::config_file::ConfigFileArgs;
use warp_cli::model::ModelArgs;
use warp_cli::share::ShareArgs;
use warp_cli::task::{MessageCommand, MessageSendArgs, MessageWatchArgs, TaskCommand};
use warp_cli::CliCommand;
use warp_core::channel::{Channel, ChannelState};
use warp_core::telemetry::TelemetryEvent;

use super::{command_requires_auth, command_to_telemetry_event, reconcile_task_harness};

const TASK_ID: &str = "00000000-0000-0000-0000-000000000001";

fn run_agent_command_for_harness(harness: Harness) -> CliCommand {
    CliCommand::Agent(AgentCommand::Run(RunAgentArgs {
        prompt_arg: PromptArg {
            prompt: Some("hello".to_string()),
            saved_prompt: None,
        },
        model: ModelArgs::default(),
        config_file: ConfigFileArgs::default(),
        skill: None,
        name: None,
        cwd: None,
        gui: false,
        share: ShareArgs { share: None },
        mcp_specs: vec![],
        mcp_servers: vec![],
        strict_mcp_startup: false,
        mcp_startup_timeout: None,
        environment: None,
        idle_on_complete: None,
        snapshot: SnapshotArgs {
            no_snapshot: false,
            snapshot_upload_timeout: None,
            snapshot_script_timeout: None,
        },
        task_id: None,
        sandboxed: false,
        bedrock_inference_role: None,
        bedrock_role_region: None,
        computer_use: HiddenComputerUseArgs::default(),
        conversation: None,
        profile: None,
        harness,
        skip_initial_turn: false,
    }))
}

fn with_hermes_native_env<T>(enabled: bool, run: impl FnOnce() -> T) -> T {
    let previous = std::env::var_os(Channel::HERMES_NATIVE_MODE_ENV);
    if enabled {
        unsafe { std::env::set_var(Channel::HERMES_NATIVE_MODE_ENV, "1") };
    } else {
        unsafe { std::env::remove_var(Channel::HERMES_NATIVE_MODE_ENV) };
    }
    ChannelState::set(ChannelState::init());
    let result = run();
    match previous {
        Some(value) => unsafe { std::env::set_var(Channel::HERMES_NATIVE_MODE_ENV, value) },
        None => unsafe { std::env::remove_var(Channel::HERMES_NATIVE_MODE_ENV) },
    }
    ChannelState::set(ChannelState::init());
    result
}

#[test]
fn logout_does_not_require_auth() {
    assert!(!command_requires_auth(&CliCommand::Logout));
}

#[test]
fn login_does_not_require_auth() {
    assert!(!command_requires_auth(&CliCommand::Login));
}

#[test]
#[serial_test::serial]
fn hermes_native_run_does_not_require_warp_login() {
    with_hermes_native_env(true, || {
        assert!(!command_requires_auth(&run_agent_command_for_harness(
            Harness::Hermes
        )));
    });
}

#[test]
#[serial_test::serial]
fn hermes_run_requires_auth_without_hermes_native_mode() {
    with_hermes_native_env(false, || {
        assert!(command_requires_auth(&run_agent_command_for_harness(
            Harness::Hermes
        )));
    });
}

#[test]
fn non_hermes_run_still_requires_auth() {
    assert!(command_requires_auth(&run_agent_command_for_harness(
        Harness::Claude
    )));
}

#[test]
fn artifact_download_requires_auth() {
    assert!(command_requires_auth(&CliCommand::Artifact(
        ArtifactCommand::Download(DownloadArtifactArgs {
            artifact_uid: "artifact-123".to_string(),
            out: None,
        },)
    )));
}

#[test]
fn run_message_send_requires_auth() {
    assert!(command_requires_auth(&CliCommand::Run(
        TaskCommand::Message(MessageCommand::Send(MessageSendArgs {
            to: vec!["run-456".to_string()],
            subject: "subject".to_string(),
            body: "body".to_string(),
            sender_run_id: "run-123".to_string(),
        }),)
    )));
}

#[test]
fn artifact_get_requires_auth() {
    assert!(command_requires_auth(&CliCommand::Artifact(
        ArtifactCommand::Get(GetArtifactArgs {
            artifact_uid: "artifact-123".to_string(),
        },)
    )));
}

#[test]
fn artifact_upload_requires_auth() {
    assert!(command_requires_auth(&CliCommand::Artifact(
        ArtifactCommand::Upload(UploadArtifactArgs {
            path: "artifact.txt".into(),
            run_id: Some("run-123".to_string()),
            conversation_id: None,
            description: None,
        },)
    )));
}

#[test]
#[serial_test::serial]
fn run_message_send_telemetry_uses_canonical_harness_from_env() {
    std::env::set_var("OZ_HARNESS", "  CLAUDE  ");
    let event = command_to_telemetry_event(&CliCommand::Run(TaskCommand::Message(
        MessageCommand::Send(MessageSendArgs {
            to: vec!["run-456".to_string()],
            subject: "subject".to_string(),
            body: "body".to_string(),
            sender_run_id: "run-123".to_string(),
        }),
    )));
    std::env::remove_var("OZ_HARNESS");

    assert_eq!(event.payload(), Some(json!({ "harness": "claude" })));
}

#[test]
#[serial_test::serial]
fn run_message_send_telemetry_supports_claude_code_alias() {
    std::env::set_var("OZ_HARNESS", "CLAUDE_CODE");
    let event = command_to_telemetry_event(&CliCommand::Run(TaskCommand::Message(
        MessageCommand::Send(MessageSendArgs {
            to: vec!["run-456".to_string()],
            subject: "subject".to_string(),
            body: "body".to_string(),
            sender_run_id: "run-123".to_string(),
        }),
    )));
    std::env::remove_var("OZ_HARNESS");

    assert_eq!(event.payload(), Some(json!({ "harness": "claude" })));
}

#[test]
#[serial_test::serial]
fn run_message_send_telemetry_supports_opencode_harness() {
    std::env::set_var("OZ_HARNESS", "opencode");
    let event = command_to_telemetry_event(&CliCommand::Run(TaskCommand::Message(
        MessageCommand::Send(MessageSendArgs {
            to: vec!["run-456".to_string()],
            subject: "subject".to_string(),
            body: "body".to_string(),
            sender_run_id: "run-123".to_string(),
        }),
    )));
    std::env::remove_var("OZ_HARNESS");

    assert_eq!(event.payload(), Some(json!({ "harness": "opencode" })));
}

#[test]
#[serial_test::serial]
fn run_message_send_telemetry_defaults_to_unknown_harness() {
    std::env::remove_var("OZ_HARNESS");
    let event = command_to_telemetry_event(&CliCommand::Run(TaskCommand::Message(
        MessageCommand::Send(MessageSendArgs {
            to: vec!["run-456".to_string()],
            subject: "subject".to_string(),
            body: "body".to_string(),
            sender_run_id: "run-123".to_string(),
        }),
    )));

    assert_eq!(event.payload(), Some(json!({ "harness": "unknown" })));
}

#[test]
fn reconcile_task_harness_adopts_task_harness_when_cli_uses_default() {
    let mut selected_harness = Harness::Oz;
    let harness = reconcile_task_harness(TASK_ID, &mut selected_harness, Harness::Claude)
        .expect("default harness should adopt task harness");

    assert_eq!(selected_harness, Harness::Claude);
    assert_eq!(harness.harness(), Harness::Claude);
}

#[test]
fn reconcile_task_harness_allows_matching_explicit_harness() {
    let mut selected_harness = Harness::Claude;
    let harness = reconcile_task_harness(TASK_ID, &mut selected_harness, Harness::Claude)
        .expect("matching harness should succeed");

    assert_eq!(selected_harness, Harness::Claude);
    assert_eq!(harness.harness(), Harness::Claude);
}

#[test]
fn reconcile_task_harness_rejects_explicit_mismatch() {
    let mut selected_harness = Harness::Gemini;
    let err = reconcile_task_harness(TASK_ID, &mut selected_harness, Harness::Claude)
        .expect_err("mismatched harness should fail");

    assert_eq!(selected_harness, Harness::Gemini);
    assert!(err.to_string().contains("Task"));
    assert!(err.to_string().contains("--harness gemini"));
    assert!(err.to_string().contains("claude"));
}

#[test]
#[serial_test::serial]
fn run_message_watch_telemetry_defaults_to_unknown_harness() {
    std::env::remove_var("OZ_HARNESS");
    let event = command_to_telemetry_event(&CliCommand::Run(TaskCommand::Message(
        MessageCommand::Watch(MessageWatchArgs {
            run_id: "run-123".to_string(),
            since_sequence: 0,
        }),
    )));

    assert_eq!(event.payload(), Some(json!({ "harness": "unknown" })));
}
