package app.darubini.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.darubini.R
import app.darubini.ui.UiState
import app.darubini.ui.theme.Tokens
import app.darubini.ui.theme.Type

/** The Muse Spark agent's tool calls, as a timeline that grows while the server reports them. */
@Composable
fun AgentScreen(state: UiState, padding: PaddingValues, onBack: () -> Unit, onReport: () -> Unit) {
    val s = state.strings
    val list = rememberLazyListState()
    LaunchedEffect(state.steps.size) {
        if (state.steps.isNotEmpty()) list.animateScrollToItem(state.steps.size)
    }
    Column(Modifier.fillMaxSize().padding(padding)) {
        Header(s.agentTitle, s.agentSub, R.drawable.ic_arrow_back, s.back, onBack)
        LazyColumn(state = list, modifier = Modifier.weight(1f).padding(horizontal = 16.dp)) {
            item {
                if (state.agentRunning) {
                    DsCard(Modifier.fillMaxWidth().padding(bottom = 16.dp), color = Tokens.PrimaryWash, border = Tokens.PrimarySoft) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(Modifier.size(22.dp), color = Tokens.Primary, strokeWidth = 2.5.dp)
                            Spacer(Modifier.width(12.dp))
                            Text(s.agentWorking, style = Type.BodyStrong, color = Tokens.PrimaryStrong)
                        }
                    }
                } else {
                    Notice(s.agentDone, null, Tone.Success, R.drawable.ic_check_circle, Modifier.padding(bottom = 16.dp))
                }
            }
            item {
                DsCard(Modifier.fillMaxWidth()) {
                    if (state.steps.isEmpty()) {
                        Text(s.agentWorking, style = Type.BodySmall, color = Tokens.TextMuted)
                    }
                    state.steps.forEachIndexed { i, step ->
                        TimelineItem(
                            title = s.tool(step.tool) + if (step.failed) " · ${s.failed}" else "",
                            detail = step.detail,
                            last = i == state.steps.size - 1,
                            tone = if (step.failed) Tone.Danger else Tone.Brand,
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))
            }
        }
        if (!state.agentRunning && state.result != null) {
            BottomActionBar {
                DsButton(s.openReport, onReport, Modifier.weight(1f), icon = R.drawable.ic_description)
            }
        }
    }
}
