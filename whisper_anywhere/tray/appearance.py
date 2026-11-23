"""What each daemon state looks like in the panel."""

from dataclasses import dataclass

from ..state import DaemonState, DaemonStatus

ICON_IDLE = "whisper-anywhere-idle"
ICON_RECORDING = "whisper-anywhere-recording"
ICON_PROCESSING = "whisper-anywhere-processing"
ICON_DIMMED = "whisper-anywhere-dimmed"


@dataclass(frozen=True)
class Appearance:
    icon_name: str
    status_text: str


DAEMON_STOPPED = Appearance(ICON_DIMMED, "daemon stopped")

_APPEARANCES: dict[DaemonState, Appearance] = {
    DaemonState.LOADING: Appearance(ICON_DIMMED, "Starting"),
    DaemonState.IDLE: Appearance(ICON_IDLE, "Idle"),
    DaemonState.RECORDING: Appearance(ICON_RECORDING, "Recording"),
    DaemonState.PROCESSING: Appearance(ICON_PROCESSING, "Processing"),
}


def appearance_for(status: DaemonStatus) -> Appearance:
    appearance = _APPEARANCES[status.state]
    if status.note:
        return Appearance(
            appearance.icon_name, f"{appearance.status_text} - {status.note}"
        )
    return appearance
