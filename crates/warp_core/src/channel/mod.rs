mod config;
mod state;

use std::fmt;

pub use config::*;
pub use state::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Channel {
    /// The official/first-party stable release.
    Stable,
    /// The official/first-party feature preview release.
    Preview,

    /// The internal-only nightly build.
    Dev,
    /// The internal-only HEAD build.
    Local,

    /// The open-source build of Warp.
    Oss,

    /// The integration test build.
    Integration,
}

impl Channel {
    /// Environment variable that puts the open-source client into Hermes-native self-host mode.
    ///
    /// In this mode the OSS client may be pointed at Joe-controlled/Tailscale-hosted Warp
    /// compatibility services via the existing `WARP_*_URL` overrides. Official release channels
    /// remain pinned to their baked-in Warp endpoints.
    pub const HERMES_NATIVE_MODE_ENV: &'static str = "WARP_HERMES_NATIVE";

    pub fn hermes_native_mode_enabled() -> bool {
        std::env::var(Self::HERMES_NATIVE_MODE_ENV)
            .ok()
            .is_some_and(|value| {
                matches!(
                    value.trim().to_ascii_lowercase().as_str(),
                    "1" | "true" | "yes" | "on"
                )
            })
    }

    /// Whether or not this channel is for internal use only
    pub fn is_dogfood(&self) -> bool {
        match self {
            Channel::Dev | Channel::Local => true,
            Channel::Stable | Channel::Preview | Channel::Integration | Channel::Oss => false,
        }
    }

    /// Whether this channel honors the `--server-root-url` / `--ws-server-url` /
    /// `--session-sharing-server-url` flags (and their `WARP_*` env-var equivalents).
    ///
    /// Release channels (`Stable`, `Preview`) ignore these overrides so official shipped builds
    /// can't be redirected away from their baked-in server URLs. Internal-only channels (`Dev`,
    /// `Local`, `Integration`) continue to honor them for local development and testing.
    ///
    /// The open-source channel additionally honors them when `WARP_HERMES_NATIVE` is enabled. That
    /// is the fork escape hatch for replacing Warp-hosted cloud surfaces with Hermes/Tailscale
    /// services without enabling redirection in official release builds.
    pub fn allows_server_url_overrides(&self) -> bool {
        match self {
            Channel::Dev | Channel::Local | Channel::Integration => true,
            Channel::Oss => Self::hermes_native_mode_enabled(),
            Channel::Stable | Channel::Preview => false,
        }
    }

    /// Returns the CLI command name corresponding to this channel.
    pub fn cli_command_name(&self) -> &'static str {
        match self {
            Channel::Stable => "oz",
            Channel::Dev => "oz-dev",
            Channel::Preview => "oz-preview",
            Channel::Local => "oz-local",
            Channel::Integration => "oz-integration",
            Channel::Oss => "warp-oss",
        }
    }
}

impl fmt::Display for Channel {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str(match self {
            Channel::Stable => "stable",
            Channel::Preview => "preview",
            Channel::Dev => "dev",
            Channel::Integration => "integration",
            Channel::Local => "local",
            Channel::Oss => "warp-oss",
        })
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Mutex, OnceLock};

    use super::Channel;

    fn env_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    #[test]
    fn oss_honors_overrides_only_in_hermes_native_mode() {
        let _guard = env_lock().lock().unwrap();

        std::env::remove_var(Channel::HERMES_NATIVE_MODE_ENV);
        assert!(!Channel::Oss.allows_server_url_overrides());

        std::env::set_var(Channel::HERMES_NATIVE_MODE_ENV, "1");
        assert!(Channel::Oss.allows_server_url_overrides());

        std::env::remove_var(Channel::HERMES_NATIVE_MODE_ENV);
    }

    #[test]
    fn official_release_channels_ignore_hermes_native_mode() {
        let _guard = env_lock().lock().unwrap();

        std::env::set_var(Channel::HERMES_NATIVE_MODE_ENV, "true");
        assert!(!Channel::Stable.allows_server_url_overrides());
        assert!(!Channel::Preview.allows_server_url_overrides());

        std::env::remove_var(Channel::HERMES_NATIVE_MODE_ENV);
    }
}
