use std::collections::HashMap;
use std::ffi::OsString;
use std::path::Path;
use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use shell_words::quote as shell_quote;
use tempfile::NamedTempFile;
use warp_cli::agent::Harness;
use warp_managed_secrets::ManagedSecretValue;
use warpui::{ModelHandle, ModelSpawner};

use super::super::terminal::{CommandHandle, TerminalDriver};
use super::super::{AgentDriver, AgentDriverError};
use super::{
    write_temp_file, HarnessRunner, JSONMCPServer, ResumePayload, SavePoint, ThirdPartyHarness,
};
use crate::ai::agent_sdk::setup_observability::{OzRunTimelineEvent, SetupClientEventReporter};
use crate::ai::ambient_agents::task::HarnessModelConfig;
use crate::ai::ambient_agents::AmbientAgentTaskId;
use crate::server::server_api::ServerApi;
use crate::terminal::CLIAgent;

pub(crate) struct HermesHarness;

const HERMES_EXIT_COMMAND: &str = "/exit";

#[cfg_attr(not(target_family = "wasm"), async_trait)]
#[cfg_attr(target_family = "wasm", async_trait(?Send))]
impl ThirdPartyHarness for HermesHarness {
    fn harness(&self) -> Harness {
        Harness::Hermes
    }

    fn cli_agent(&self) -> CLIAgent {
        CLIAgent::Hermes
    }

    fn install_docs_url(&self) -> Option<&'static str> {
        Some("https://hermes-agent.nousresearch.com/docs")
    }

    fn build_runner(
        &self,
        prompt: &str,
        system_prompt: Option<&str>,
        resumption_prompt: Option<&str>,
        context: Option<&str>,
        _working_dir: &Path,
        _task_id: Option<AmbientAgentTaskId>,
        _server_api: Arc<ServerApi>,
        terminal_driver: ModelHandle<TerminalDriver>,
        _resume: Option<ResumePayload>,
        _resolved_env_vars: &HashMap<OsString, OsString>,
        _resolved_secrets: &HashMap<String, ManagedSecretValue>,
        _resolved_mcp_servers: &HashMap<String, JSONMCPServer>,
        third_party_harness_model_config: Option<&HarnessModelConfig>,
    ) -> Result<Box<dyn HarnessRunner>, AgentDriverError> {
        let mut parts: Vec<&str> = Vec::new();
        if let Some(system_prompt) = system_prompt.filter(|value| !value.is_empty()) {
            parts.push(system_prompt);
        }
        if let Some(resumption_prompt) = resumption_prompt.filter(|value| !value.is_empty()) {
            parts.push(resumption_prompt);
        }
        if let Some(context) = context.filter(|value| !value.is_empty()) {
            parts.push(context);
        }
        parts.push(prompt);
        let owned_prompt = parts.join("\n\n");

        Ok(Box::new(HermesHarnessRunner::new(
            self.cli_agent().command_prefix(),
            &owned_prompt,
            terminal_driver,
            third_party_harness_model_config,
        )?))
    }
}

fn hermes_command(cli_name: &str, prompt_path: &str, model_id: Option<&str>) -> String {
    let quoted_prompt_path = shell_quote(prompt_path);
    match model_id.filter(|id| !id.is_empty()) {
        Some(model_id) => {
            let quoted_model = shell_quote(model_id);
            format!(
                "{cli_name} chat --quiet --model {quoted_model} --query \"$(cat {quoted_prompt_path})\""
            )
        }
        None => format!("{cli_name} chat --quiet --query \"$(cat {quoted_prompt_path})\""),
    }
}

struct HermesHarnessRunner {
    command: String,
    cli_name: String,
    _temp_prompt_file: NamedTempFile,
    terminal_driver: ModelHandle<TerminalDriver>,
}

impl HermesHarnessRunner {
    fn new(
        cli_command: &str,
        prompt: &str,
        terminal_driver: ModelHandle<TerminalDriver>,
        model_config: Option<&HarnessModelConfig>,
    ) -> Result<Self, AgentDriverError> {
        let temp_file = write_temp_file("hermes_prompt_", prompt, ".txt")?;
        let prompt_path = temp_file.path().display().to_string();
        let command = hermes_command(
            cli_command,
            &prompt_path,
            model_config.map(|config| config.model_id.as_str()),
        );

        Ok(Self {
            command,
            cli_name: cli_command.to_string(),
            _temp_prompt_file: temp_file,
            terminal_driver,
        })
    }
}

#[cfg_attr(not(target_family = "wasm"), async_trait)]
#[cfg_attr(target_family = "wasm", async_trait(?Send))]
impl HarnessRunner for HermesHarnessRunner {
    fn harness_name(&self) -> &str {
        &self.cli_name
    }

    async fn start(
        &self,
        foreground: &ModelSpawner<AgentDriver>,
        setup_events: &SetupClientEventReporter,
    ) -> Result<CommandHandle, AgentDriverError> {
        let command = self.command.clone();
        let terminal_driver = self.terminal_driver.clone();
        let command_handle = foreground
            .spawn(move |_, ctx| {
                terminal_driver.update(ctx, |driver, ctx| driver.execute_command(&command, ctx))
            })
            .await??
            .await?;

        setup_events
            .post_timeline_event(OzRunTimelineEvent::AgentStarted)
            .await;

        Ok(command_handle)
    }

    async fn save_conversation(
        &self,
        _save_point: SavePoint,
        _foreground: &ModelSpawner<AgentDriver>,
    ) -> Result<()> {
        Ok(())
    }

    async fn exit(&self, foreground: &ModelSpawner<AgentDriver>) -> Result<()> {
        let terminal_driver = self.terminal_driver.clone();
        foreground
            .spawn(move |_, ctx| {
                terminal_driver.update(ctx, |driver, ctx| {
                    driver.send_text_to_cli(HERMES_EXIT_COMMAND.to_string(), ctx);
                });
            })
            .await
            .map_err(|_| anyhow::anyhow!("Agent driver dropped while sending /exit"))
    }
}

#[cfg(test)]
mod tests {
    use super::hermes_command;

    #[test]
    fn hermes_command_passes_model_when_selected() {
        assert_eq!(
            hermes_command("hermes", "/tmp/prompt.txt", Some("hermes/migi-default")),
            "hermes chat --quiet --model hermes/migi-default --query \"$(cat /tmp/prompt.txt)\""
        );
    }

    #[test]
    fn hermes_command_quotes_model_when_selected() {
        assert_eq!(
            hermes_command("hermes", "/tmp/prompt.txt", Some("hermes/migi's default")),
            "hermes chat --quiet --model 'hermes/migi'\\''s default' --query \"$(cat /tmp/prompt.txt)\""
        );
    }

    #[test]
    fn hermes_command_omits_empty_model() {
        assert_eq!(
            hermes_command("hermes", "/tmp/prompt.txt", Some("")),
            "hermes chat --quiet --query \"$(cat /tmp/prompt.txt)\""
        );
    }
}
