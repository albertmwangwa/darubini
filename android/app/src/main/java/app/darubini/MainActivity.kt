package app.darubini

import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.ContentTransform
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.IntOffset
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.darubini.ui.DarubiniViewModel
import app.darubini.ui.Screen
import app.darubini.ui.screens.AgentScreen
import app.darubini.ui.screens.CaptureScreen
import app.darubini.ui.screens.ReportScreen
import app.darubini.ui.screens.SettingsScreen
import app.darubini.ui.screens.StartScreen
import app.darubini.ui.theme.DarubiniTheme

class MainActivity : ComponentActivity() {
    private val model: DarubiniViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The design system is light only, so the system bars always use dark icons.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT),
        )
        setContent {
            DarubiniTheme { DarubiniApp(model) }
        }
    }
}

/** Screen order, so forward moves slide in from the right and back moves reverse it. */
private val DEPTH = mapOf(Screen.Start to 0, Screen.Settings to 1, Screen.Capture to 1, Screen.Agent to 2, Screen.Report to 3)

@Composable
private fun DarubiniApp(model: DarubiniViewModel) {
    val state by model.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.message) {
        state.message?.let {
            snackbar.showSnackbar(it)
            model.dismissMessage()
        }
    }
    BackHandler(enabled = state.screen != Screen.Start) { model.back() }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.surface,
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        val spatial = MaterialTheme.motionScheme.defaultSpatialSpec<IntOffset>()
        val effects = MaterialTheme.motionScheme.defaultEffectsSpec<Float>()
        AnimatedContent(
            targetState = state.screen,
            transitionSpec = {
                val from = DEPTH.getValue(initialState)
                val to = DEPTH.getValue(targetState)
                when {
                    // As in the canvas flow: the report expands out of the last agent step and fades when closed.
                    targetState == Screen.Report -> ContentTransform(scaleIn(effects, 0.92f) + fadeIn(effects), fadeOut(effects))
                    initialState == Screen.Report -> ContentTransform(fadeIn(effects), fadeOut(effects))
                    else -> {
                        val dir = if (to >= from) 1 else -1
                        slideInHorizontally(spatial) { it * dir } togetherWith slideOutHorizontally(spatial) { -it * dir }
                    }
                }
            },
            label = "screen",
        ) { screen ->
            when (screen) {
                Screen.Start -> StartScreen(state, padding, model::setLanguage, model::startSlide) { model.go(Screen.Settings) }
                Screen.Settings -> SettingsScreen(state, padding, model::back, model::setServer, model::checkServer, model::setLanguage)
                Screen.Capture -> CaptureScreen(
                    state,
                    padding,
                    onBack = model::back,
                    onPhoto = model::uploadPhoto,
                    onClip = model::uploadClip,
                    onPickedVideo = model::uploadPickedVideo,
                    onFinish = model::finishSlide,
                    onMessage = model::say,
                )
                Screen.Agent -> AgentScreen(state, padding, model::back) { model.go(Screen.Report) }
                Screen.Report -> ReportScreen(state, padding, onClose = model::back, onAgain = model::startSlide)
            }
        }
    }
}
