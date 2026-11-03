package app.darubini.data

import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** A failed request, with the server's `detail` when it sent one. */
class ApiException(message: String) : IOException(message)

/** The `darubini serve` capture API, as used by the web phone app. */
class DarubiniApi(baseUrl: String, private val http: OkHttpClient = defaultClient) {
    private val base: HttpUrl = normalise(baseUrl).toHttpUrl()

    suspend fun health(): Boolean = get("health").optString("status") == "ok"

    suspend fun createSession(): SessionStart = Parse.session(post("v1/sessions", ByteArray(0).toRequestBody()))

    suspend fun uploadField(sessionId: String, jpeg: ByteArray): CaptureReply =
        Parse.capture(post("v1/sessions/$sessionId/fields", multipart("field.jpg", jpeg.toRequestBody(JPEG))))

    suspend fun uploadClip(sessionId: String, clip: File): CaptureReply =
        Parse.capture(post("v1/sessions/$sessionId/clips", multipart(clip.name, clip.asRequestBody(MP4))))

    suspend fun sendVoice(sessionId: String, audio: File): VoiceReply =
        Parse.voice(post("v1/sessions/$sessionId/voice", multipart(audio.name, audio.asRequestBody(M4A))))

    suspend fun startReport(sessionId: String, language: String): ReportJob =
        Parse.job(post("v1/sessions/$sessionId/report?language=$language", ByteArray(0).toRequestBody()))

    suspend fun report(sessionId: String): ReportJob = Parse.job(get("v1/sessions/$sessionId/report"))

    private fun multipart(name: String, body: RequestBody): RequestBody =
        MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file", name, body).build()

    private suspend fun get(path: String) = call(Request.Builder().url(url(path)).get().build())

    private suspend fun post(path: String, body: RequestBody) = call(Request.Builder().url(url(path)).post(body).build())

    private fun url(path: String): HttpUrl = base.resolve(path) ?: throw ApiException("bad server address")

    private suspend fun call(request: Request): JSONObject = withContext(Dispatchers.IO) {
        http.newCall(request).execute().use { response ->
            val text = response.body.string()
            val json = runCatching { JSONObject(text) }.getOrNull()
            if (!response.isSuccessful) {
                val detail = json?.opt("detail")?.toString() ?: response.message.ifEmpty { "HTTP ${response.code}" }
                throw ApiException(detail)
            }
            json ?: throw ApiException("the server did not reply with JSON")
        }
    }

    companion object {
        private val JPEG = "image/jpeg".toMediaType()
        private val MP4 = "video/mp4".toMediaType()
        private val M4A = "audio/mp4".toMediaType()

        /** Clip analysis takes ~30 s and SAM can be slower, so reads wait generously. */
        val defaultClient: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS)
            .build()

        /** Accepts "192.168.1.20:8000" as well as a full URL; always ends in "/". */
        fun normalise(address: String): String {
            var a = address.trim()
            if (!a.startsWith("http://") && !a.startsWith("https://")) a = "http://$a"
            return if (a.endsWith("/")) a else "$a/"
        }
    }
}
