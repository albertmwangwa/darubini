package app.darubini.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.darubini.R
import app.darubini.ui.UiState
import app.darubini.ui.theme.Radius
import app.darubini.ui.theme.Tokens
import app.darubini.ui.theme.Type

private val LANGUAGES = listOf("en" to "English", "sw" to "Kiswahili")

@Composable
fun SettingsScreen(
    state: UiState,
    padding: PaddingValues,
    onBack: () -> Unit,
    onServer: (String) -> Unit,
    onCheck: () -> Unit,
    onLanguage: (String) -> Unit,
) {
    val s = state.strings
    var address by remember { mutableStateOf(state.server) }
    Column(Modifier.fillMaxSize().padding(padding)) {
        Header(s.settings, null, R.drawable.ic_arrow_back, s.back, onBack)
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionHeader(s.serverAddress)
            OutlinedTextField(
                value = address,
                onValueChange = {
                    address = it
                    onServer(it)
                },
                textStyle = Type.BodyLarge,
                leadingIcon = { Symbol(R.drawable.ic_dns, tint = Tokens.TextMuted) },
                singleLine = true,
                shape = RoundedCornerShape(Radius.Md),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedContainerColor = Tokens.Card,
                    unfocusedContainerColor = Tokens.Card,
                    unfocusedBorderColor = Tokens.BorderInput,
                    focusedBorderColor = Tokens.Ring,
                    cursorColor = Tokens.Primary,
                ),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
                modifier = Modifier.fillMaxWidth(),
            )
            Text(s.serverHelp, style = Type.Caption, color = Tokens.TextMuted)
            Row(verticalAlignment = Alignment.CenterVertically) {
                DsButton(s.testConnection, onCheck, kind = ButtonKind.Soft, size = ButtonSize.M, icon = R.drawable.ic_wifi_tethering)
                Spacer(Modifier.width(12.dp))
                ServerStatus(state)
            }
            SectionHeader(s.language)
            LANGUAGES.forEach { (code, name) ->
                OptionTile(name, state.language == code) { onLanguage(code) }
            }
        }
    }
}

/** The Figma Option tile: a white row with a round check, outlined in green when chosen. */
@Composable
private fun OptionTile(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(Radius.R16),
        color = if (selected) Tokens.PrimaryWash else Tokens.Card,
        border = BorderStroke(if (selected) 1.5.dp else 1.dp, if (selected) Tokens.Ring else Tokens.Border),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(22.dp).clip(CircleShape)
                    .background(if (selected) Tokens.Primary else Tokens.Card)
                    .border(1.5.dp, if (selected) Tokens.Primary else Tokens.BorderStrong, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                if (selected) Icon(painterResource(R.drawable.ic_check), null, Modifier.size(14.dp), tint = Tokens.OnPrimary)
            }
            Spacer(Modifier.width(12.dp))
            Text(label, style = Type.BodyStrong, color = Tokens.Foreground)
        }
    }
}
