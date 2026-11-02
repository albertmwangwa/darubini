package app.darubini.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.darubini.R
import app.darubini.ui.Health
import app.darubini.ui.UiState
import app.darubini.ui.theme.Radius
import app.darubini.ui.theme.Tokens
import app.darubini.ui.theme.Type

@Composable
fun StartScreen(
    state: UiState,
    padding: PaddingValues,
    onLanguage: (String) -> Unit,
    onBegin: () -> Unit,
    onSettings: () -> Unit,
) {
    val s = state.strings
    Column(Modifier.fillMaxSize().padding(padding)) {
        Row(
            Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconDisc(R.drawable.ic_biotech, 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(s.greeting, style = Type.Caption, color = Tokens.TextMuted)
                Text("Darubini", style = Type.Title, color = Tokens.Foreground)
            }
            CircleIconButton(R.drawable.ic_settings, s.settings, onSettings)
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ServerStatus(state)
            DsCard(Modifier.fillMaxWidth(), radius = Radius.Card, color = Tokens.Primary, border = null, padding = 20.dp) {
                Text(s.tagline.uppercase(), style = Type.Eyebrow, color = Tokens.LimeBright)
                Spacer(Modifier.height(8.dp))
                Text(s.welcome, style = Type.PageTitle, color = Tokens.OnPrimary)
                Spacer(Modifier.height(8.dp))
                Text(s.intro, style = Type.BodySmall, color = Tokens.PrimarySoft)
            }
            SectionHeader(s.howItWorks)
            CaptureRow(R.drawable.ic_photo_camera, s.photo, s.photoBody)
            CaptureRow(R.drawable.ic_videocam, s.clip, s.panBody)
            CaptureRow(R.drawable.ic_auto_awesome, s.agentTitle, s.agentBody)
            SectionHeader(s.language)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                LanguageChip("English", state.language == "en") { onLanguage("en") }
                LanguageChip("Kiswahili", state.language == "sw") { onLanguage("sw") }
            }
            Spacer(Modifier.height(4.dp))
        }
        Disclaimer(s.disclaimer)
        BottomActionBar {
            DsButton(
                s.begin,
                onBegin,
                Modifier.weight(1f),
                icon = R.drawable.ic_play_arrow,
                busy = state.busy,
            )
        }
    }
}

/** Connection to `darubini serve`, as colour + word like the Figma sync badge. */
@Composable
fun ServerStatus(state: UiState) {
    val s = state.strings
    Row(verticalAlignment = Alignment.CenterVertically) {
        when (state.health) {
            Health.Ok -> Badge(s.connected, Tone.Success, R.drawable.ic_check_circle)
            Health.Failed -> Badge(s.offline, Tone.Offline, R.drawable.ic_cloud_off)
            Health.Checking, Health.Unknown -> Badge(s.checking, Tone.Neutral, R.drawable.ic_schedule)
        }
        Spacer(Modifier.width(8.dp))
        Text(
            "${s.server} · ${state.server.removePrefix("http://").removePrefix("https://")}",
            style = Type.Caption,
            color = Tokens.TextMuted,
            maxLines = 1,
        )
    }
}

/** The Figma Chip: pill, white with a border, or soft green with a check when selected. */
@Composable
fun LanguageChip(label: String, selected: Boolean, onClick: () -> Unit) {
    DsButton(
        label,
        onClick,
        kind = if (selected) ButtonKind.Soft else ButtonKind.Outline,
        size = ButtonSize.M,
        icon = if (selected) R.drawable.ic_check else null,
    )
}
