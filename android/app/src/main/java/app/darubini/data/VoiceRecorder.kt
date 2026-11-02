package app.darubini.data

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/** Push-to-talk recording: AAC in an MP4 file, 16 kHz mono, which the server converts to WAV. */
class VoiceRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var file: File? = null

    val recording: Boolean get() = recorder != null

    fun start() {
        stop()?.delete()
        val out = File(File(context.cacheDir, "captures").apply { mkdirs() }, "voice.m4a")
        out.delete()
        val r = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(context) else @Suppress("DEPRECATION") MediaRecorder()
        try {
            r.setAudioSource(MediaRecorder.AudioSource.MIC)
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            r.setAudioChannels(1)
            r.setAudioSamplingRate(16_000)
            r.setAudioEncodingBitRate(32_000)
            r.setMaxDuration(MAX_MS)
            r.setOutputFile(out.path)
            r.prepare()
            r.start()
        } catch (e: Exception) {
            r.release()
            throw e
        }
        recorder = r
        file = out
    }

    /** Stop and return the recording, or null when nothing usable was recorded. */
    fun stop(): File? {
        val r = recorder ?: return null
        recorder = null
        val ok = runCatching { r.stop() }.isSuccess // fails when stopped within a few ms of start
        r.release()
        return file?.takeIf { ok && it.length() > 0 }
    }

    companion object {
        const val MAX_MS = 20_000
    }
}
