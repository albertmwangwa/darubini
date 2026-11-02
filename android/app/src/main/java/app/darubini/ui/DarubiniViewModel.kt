package app.darubini.ui

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.core.content.edit
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.darubini.data.AgentStep
import app.darubini.data.ClipReply
import app.darubini.data.DarubiniApi
import app.darubini.data.FieldReply
import app.darubini.data.Images
import app.darubini.data.Next
import app.darubini.data.ReportResult
import app.darubini.data.Running
import app.darubini.data.VoiceRecorder
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Start, Capture, Agent, Report, Settings }

enum class Health { Unknown, Checking, Ok, Failed }

data class UiState(
    val screen: Screen = Screen.Start,
    val language: String = "en",
    val server: String = DEFAULT_SERVER,
    val health: Health = Health.Unknown,
    val sessionId: String? = null,
    val running: Running? = null,
    val next: Next? = null,
    val lastField: FieldReply? = null,
    val lastImage: Bitmap? = null,
    val lastClip: ClipReply? = null,
    val fieldsKept: Int = 0,
    val busy: Boolean = false,
    val message: String? = null,
    val steps: List<AgentStep> = emptyList(),
    val agentRunning: Boolean = false,
    val result: ReportResult? = null,
    val listening: Boolean = false,
    /** Set when a spoken "next field" or "retake" should open the camera; the screen clears it. */
    val cameraRequested: Boolean = false,
    val voiceNotes: List<String> = emptyList(),
) {
    val strings: Strings get() = stringsFor(language)
}

/** The emulator's address for the host machine; set the real one in Settings. */
const val DEFAULT_SERVER = "http://10.0.2.2:8000"
private const val POLL_MS = 1500L

class DarubiniViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("darubini", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(
        UiState(
            language = prefs.getString("language", "en") ?: "en",
            server = prefs.getString("server", DEFAULT_SERVER) ?: DEFAULT_SERVER,
        ),
    )
    val state: StateFlow<UiState> = _state.asStateFlow()
    private var poll: Job? = null
    private val recorder = VoiceRecorder(app)

    init {
        checkServer()
    }

    private val api: DarubiniApi get() = DarubiniApi(_state.value.server)
    private val s: Strings get() = _state.value.strings

    fun go(screen: Screen) = _state.update { it.copy(screen = screen, message = null) }

    fun back() = _state.update {
        val to = when (it.screen) {
            Screen.Capture, Screen.Settings, Screen.Report -> Screen.Start
            Screen.Agent -> Screen.Capture
            Screen.Start -> Screen.Start
        }
        it.copy(screen = to, message = null)
    }

    fun dismissMessage() = _state.update { it.copy(message = null) }

    fun say(text: String) = _state.update { it.copy(message = text) }

    fun setLanguage(code: String) {
        prefs.edit { putString("language", code) }
        _state.update { it.copy(language = code) }
    }

    fun setServer(address: String) {
        prefs.edit { putString("server", address.trim()) }
        _state.update { it.copy(server = address.trim(), health = Health.Unknown) }
    }

    fun checkServer() {
        _state.update { it.copy(health = Health.Checking) }
        viewModelScope.launch {
            val ok = runCatching { api.health() }.getOrDefault(false)
            _state.update { it.copy(health = if (ok) Health.Ok else Health.Failed) }
        }
    }

    fun startSlide() = work {
        val session = api.createSession()
        _state.update {
            it.copy(
                screen = Screen.Capture,
                sessionId = session.sessionId,
                running = session.running,
                next = null,
                lastField = null,
                lastImage = null,
                lastClip = null,
                fieldsKept = 0,
                steps = emptyList(),
                result = null,
                voiceNotes = emptyList(),
            )
        }
    }

    /** First tap starts recording; the second sends it to Muse Voice Transcribe and acts on it. */
    fun toggleListening() {
        if (!_state.value.listening) {
            try {
                recorder.start()
                _state.update { it.copy(listening = true, message = null) }
            } catch (e: Exception) {
                say(s.error + (e.message ?: e.javaClass.simpleName))
            }
            return
        }
        val audio = recorder.stop()
        _state.update { it.copy(listening = false) }
        if (audio == null) {
            say(s.notUnderstood(""))
            return
        }
        work {
            val sid = _state.value.sessionId ?: return@work
            val reply = api.sendVoice(sid, audio)
            _state.update { it.copy(voiceNotes = reply.voiceNotes) }
            when (reply.action) {
                "next", "retake" -> _state.update { it.copy(cameraRequested = true) }
                "finish" -> finishAfterWork = true
                "note" -> say(s.noteSaved(reply.note.orEmpty()))
                else -> say(s.notUnderstood(reply.transcript))
            }
        }
    }

    fun cameraOpened() = _state.update { it.copy(cameraRequested = false) }

    private var finishAfterWork = false

    override fun onCleared() {
        recorder.stop()?.delete()
    }

    fun uploadPhoto(uri: Uri) = work {
        val sid = _state.value.sessionId ?: return@work
        val (bitmap, jpeg) = withContext(Dispatchers.Default) {
            val b = Images.loadDownscaled(getApplication(), uri)
            b to Images.jpeg(b)
        }
        val reply = api.uploadField(sid, jpeg)
        val field = reply.field
        _state.update {
            it.copy(
                running = reply.running,
                next = reply.next,
                lastField = field,
                lastImage = bitmap,
                lastClip = null,
                fieldsKept = it.fieldsKept + if (field?.kept == true) 1 else 0,
            )
        }
    }

    fun uploadClip(file: File) = work { sendClip(file) }

    fun uploadPickedVideo(uri: Uri) = work {
        sendClip(withContext(Dispatchers.IO) { Images.copyToCache(getApplication(), uri, "picked.mp4") })
    }

    private suspend fun sendClip(file: File) {
        val sid = _state.value.sessionId ?: return
        if (file.length() > Images.MAX_CLIP_BYTES) {
            say(s.clipTooLarge)
            return
        }
        val reply = api.uploadClip(sid, file)
        _state.update {
            it.copy(
                running = reply.running,
                next = reply.next,
                lastClip = reply.clip,
                lastField = null,
                lastImage = null,
                fieldsKept = it.fieldsKept + 1,
            )
        }
    }

    fun finishSlide() {
        val st = _state.value
        val sid = st.sessionId ?: return
        if (st.fieldsKept == 0) {
            say(s.noFields)
            return
        }
        _state.update { it.copy(screen = Screen.Agent, steps = emptyList(), result = null, agentRunning = true, message = null) }
        poll?.cancel()
        poll = viewModelScope.launch {
            try {
                var job = api.startReport(sid, st.language)
                while (isActive) {
                    val current = job
                    _state.update { it.copy(steps = current.steps) }
                    if (!current.running) break
                    delay(POLL_MS)
                    job = api.report(sid)
                }
                _state.update { it.copy(agentRunning = false, result = job.result) }
                if (job.error != null) {
                    say(s.error + job.error)
                } else if (job.result != null) {
                    delay(800)
                    go(Screen.Report)
                }
            } catch (e: Exception) {
                _state.update { it.copy(agentRunning = false, message = s.error + (e.message ?: e.javaClass.simpleName)) }
            }
        }
    }

    /** Run one request with the busy indicator, turning failures into a message. */
    private fun work(block: suspend () -> Unit) {
        if (_state.value.busy) return
        _state.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            try {
                block()
            } catch (e: Exception) {
                say(s.error + (e.message ?: e.javaClass.simpleName))
            } finally {
                _state.update { it.copy(busy = false) }
            }
            if (finishAfterWork) {
                finishAfterWork = false
                finishSlide()
            }
        }
    }
}
