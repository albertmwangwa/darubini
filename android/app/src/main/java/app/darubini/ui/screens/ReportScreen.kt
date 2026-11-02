package app.darubini.ui.screens

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.darubini.R
import app.darubini.data.ReportResult
import app.darubini.ui.UiState
import app.darubini.ui.theme.Tokens
import app.darubini.ui.theme.Type

@Composable
fun ReportScreen(state: UiState, padding: PaddingValues, onClose: () -> Unit, onAgain: () -> Unit) {
    val s = state.strings
    val result = state.result
    val context = LocalContext.current
    val share = {
        if (result != null) {
            val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, result.text)
            context.startActivity(Intent.createChooser(send, s.share))
        }
    }
    Column(Modifier.fillMaxSize().padding(padding)) {
        Header(s.report, null, R.drawable.ic_close, s.close, onClose)
        if (result == null) return@Column
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Outcome(state, result)
            AuditNotice(state, result)
            Facts(state, result)
            result.narrative?.let { CopilotCard(s.agentSummary, it) }
            if (result.excluded.isNotEmpty()) {
                SectionHeader(s.excluded)
                result.excluded.forEach { (field, why) ->
                    CaptureRow(R.drawable.ic_block, field, why, tone = Tone.Neutral)
                }
            }
            if (result.voiceNotes.isNotEmpty()) {
                SectionHeader(s.voiceNotes)
                result.voiceNotes.forEach { CaptureRow(R.drawable.ic_mic, it, null, tone = Tone.Neutral) }
            }
            FullReport(state, result)
            Disclaimer(s.disclaimer)
        }
        BottomActionBar {
            DsButton(s.share, share, Modifier.weight(1f), ButtonKind.Outline, icon = R.drawable.ic_share)
            DsButton(s.newSlide, onAgain, Modifier.weight(1f), icon = R.drawable.ic_add, busy = state.busy)
        }
    }
}

/** The headline, laid out like the Figma "Visit accepted" screen: a disc, a number, a line. */
@Composable
private fun Outcome(state: UiState, result: ReportResult) {
    val s = state.strings
    val f = result.slide
    val flagged = result.audit?.flagged == true
    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        if (flagged) IconDisc(R.drawable.ic_warning, 80.dp, Tone.Warning) else IconDisc(R.drawable.ic_check_circle, 80.dp)
        Spacer(Modifier.height(16.dp))
        val density = f.densityPerUl
        Text(
            if (density != null) "${s.number(density)} ${s.perUl}" else s.noDensity,
            style = Type.PageTitle,
            color = Tokens.Foreground,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            s.countLine(f.parasites, f.wbcs, f.usableFields, f.fieldsExamined),
            style = Type.Body,
            color = Tokens.TextMuted,
            textAlign = TextAlign.Center,
        )
    }
}

/** The second-reader audit: a danger notice when it flags the count, otherwise an info one. */
@Composable
private fun AuditNotice(state: UiState, result: ReportResult) {
    val s = state.strings
    val text = result.auditText ?: return
    if (result.audit?.flagged == true) {
        Notice(s.inflated, text, Tone.Danger, R.drawable.ic_warning)
    } else {
        Notice(s.auditTitle, text, Tone.Info, R.drawable.ic_fact_check)
    }
}

@Composable
private fun Facts(state: UiState, result: ReportResult) {
    val s = state.strings
    val f = result.slide
    val audit = result.audit
    DsCard(Modifier.fillMaxWidth(), padding = 16.dp) {
        KeyValueRow(s.parasitesCounted) { ValueText(s.number(f.parasites)) }
        KeyValueRow(s.wbcsCounted) { ValueText(s.number(f.wbcs)) }
        KeyValueRow(s.fieldsUsable) { ValueText(s.usableOf(f.usableFields, f.fieldsExamined)) }
        if (audit != null && audit.sampled > 0) {
            KeyValueRow(s.audit) {
                Badge(
                    s.auditValue(audit.confirmed, audit.sampled),
                    if (audit.flagged) Tone.Danger else Tone.Success,
                    if (audit.flagged) R.drawable.ic_warning else R.drawable.ic_check_circle,
                )
            }
        }
        KeyValueRow(s.status, last = true) {
            Badge(
                s.statusWord(f.status),
                if (f.status == "continue") Tone.Warning else Tone.Success,
                if (f.status == "continue") R.drawable.ic_schedule else R.drawable.ic_check_circle,
            )
        }
    }
}

/** The plain-text report, folded away until asked for. */
@Composable
private fun FullReport(state: UiState, result: ReportResult) {
    val s = state.strings
    var open by rememberSaveable { mutableStateOf(false) }
    DsCard(Modifier.fillMaxWidth(), radius = 16.dp) {
        SectionHeader(s.fullReport, Modifier.padding(bottom = 4.dp)) {
            DsButton(if (open) s.hide else s.show, { open = !open }, kind = ButtonKind.Ghost, size = ButtonSize.S)
        }
        if (open) {
            Text(result.report, style = Type.BodySmall.copy(fontFamily = FontFamily.Monospace), color = Tokens.ForegroundSoft)
            if (result.notes.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text(result.notes.joinToString(" "), style = Type.Caption, color = Tokens.TextMuted)
            }
        }
    }
}
