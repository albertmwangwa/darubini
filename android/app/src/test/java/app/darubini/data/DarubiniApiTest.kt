package app.darubini.data

import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

private const val RUNNING =
    """{"fields_examined": 3, "usable_fields": 2, "parasites": 41, "wbcs": 37, "status": "continue",
    "density_per_ul": 8864.86, "reason": "continue to 200 WBC", "fields_remaining": null,
    "stop_rule_met": false, "wbc_target": 200}"""

private const val FIELD_REPLY =
    """{"field": {"field_id": "field-003", "kept": false, "usable": false,
    "flags": ["blocking: out of focus", "low contrast"], "parasites": 4, "wbcs": 2,
    "blocking_text": {"en": ["out of focus"], "sw": ["picha haijalenga vizuri (focus)"]},
    "width": 2048, "height": 1536, "detections": [
      {"class": "parasite", "box": [10, 20, 30, 40], "score": 0.91},
      {"class": "wbc", "box": [100.5, 200, 160, 260], "score": 0.88}]},
    "running": $RUNNING, "next": {"action": "retake", "reason": "quality"}}"""

private const val CLIP_REPLY =
    """{"clip": {"field_id": "clip-004", "frames": 60, "keyframes": 6, "tracker": "sam3.1",
    "parasites": 18, "wbcs": 5, "naive_parasites": 47, "naive_wbcs": 14, "width": 1280, "height": 720},
    "running": $RUNNING, "next": {"action": "next", "reason": "continue to 200 WBC"}}"""

private const val JOB_RUNNING =
    """{"state": "running", "result": null, "error": null, "steps": [
      {"tool": "examine_next_fields", "arguments": {"count": 4},
       "result": {"examined": 4, "running": {"parasites": 620, "wbcs": 205, "status": "complete"}}},
      {"tool": "review_field", "arguments": {"field_id": "field-002"},
       "result": {"field_id": "field-002", "usable": false, "issues": ["soft focus", "pale staining"]}},
      {"tool": "exclude_field", "arguments": {"field_id": "field-002", "reason": "blurry"}, "result": {"excluded": "field-002"}},
      {"tool": "audit_parasites", "arguments": {}, "result": {"sampled": 20, "confirmed": 4, "flagged": true}},
      {"tool": "examine_next_fields", "arguments": {"count": 3}, "result": {"error": "segmentation failed: 503"}}]}"""

private const val JOB_DONE =
    """{"state": "done", "steps": [], "error": null, "result": {
      "language": "sw", "report": "Sehemu zilizochunguzwa: 20", "narrative": "  Tulichunguza sehemu 20.  ",
      "audit": {"sampled": 20, "confirmed": 4, "confirmed_percent": 20, "audited_parasites": 103, "flagged": true},
      "audit_text": "Tahadhari: hesabu huenda imeongezeka.",
      "excluded": {"field-002": "blurry"},
      "slide": {"fields_examined": 20, "usable_fields": 18, "parasites": 620, "wbcs": 205,
                "status": "complete", "density_per_ul": 24195.12, "reason": "620 at 205"},
      "finished_by_agent": true, "notes": [], "text": "full text"}}"""

class ParseTest {
    @Test
    fun fieldReplyKeepsDetectionsAndBlockingFlags() {
        val r = Parse.capture(JSONObject(FIELD_REPLY))
        val field = r.field!!
        assertFalse(field.kept)
        assertEquals(listOf("out of focus"), field.blocking("en"))
        assertEquals(listOf("picha haijalenga vizuri (focus)"), field.blocking("sw"))
        assertEquals(2, field.detections.size)
        assertTrue(field.detections[0].isParasite)
        assertEquals(100.5f, field.detections[1].x0)
        assertEquals("retake", r.next.action)
        assertEquals(8865, r.running.densityPerUl)
        assertEquals(37f / 200, r.running.progress, 1e-6f)
        assertNull(r.clip)
    }

    @Test
    fun blockingFallsBackToFlagsFromAnOlderServer() {
        val o = JSONObject(FIELD_REPLY).getJSONObject("field").apply { remove("blocking_text") }
        assertEquals(listOf("out of focus"), Parse.field(o).blocking("sw"))
    }

    @Test
    fun clipReply() {
        val clip = Parse.capture(JSONObject(CLIP_REPLY)).clip!!
        assertEquals(18, clip.parasites)
        assertEquals(47, clip.naiveParasites)
        assertEquals("sam3.1", clip.tracker)
    }

    @Test
    fun stepDetailsMatchTheWebApp() {
        val job = Parse.job(JSONObject(JOB_RUNNING))
        assertTrue(job.running)
        assertEquals(
            listOf("4 → 620 / 205", "field-002: ✗ soft focus, pale staining", "field-002: blurry", "4 / 20", "segmentation failed: 503"),
            job.steps.map { it.detail },
        )
        assertEquals(listOf(false, false, false, false, true), job.steps.map { it.failed })
    }

    @Test
    fun finishedReport() {
        val result = Parse.job(JSONObject(JOB_DONE)).result!!
        assertEquals("Tulichunguza sehemu 20.", result.narrative)
        assertTrue(result.audit!!.flagged)
        assertEquals(mapOf("field-002" to "blurry"), result.excluded)
        assertEquals(24195, result.slide.densityPerUl)
        assertEquals(18, result.slide.usableFields)
    }

    @Test
    fun noDensityBeforeAnyWbc() {
        val r = Parse.running(JSONObject("""{"parasites": 3, "wbcs": 0, "density_per_ul": null, "wbc_target": 200}"""))
        assertNull(r.densityPerUl)
        assertEquals(0f, r.progress)
    }
}

class DarubiniApiTest {
    private lateinit var server: MockWebServer

    @Before
    fun start() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun stop() = server.close()

    private fun api() = DarubiniApi(server.url("/").toString())

    private fun reply(code: Int, body: String) = server.enqueue(MockResponse.Builder().code(code).body(body).build())

    @Test
    fun uploadsTheFieldAsMultipart() = runTest {
        reply(200, FIELD_REPLY)
        val r = api().uploadField("abc", byteArrayOf(1, 2, 3))
        assertEquals("field-003", r.field!!.fieldId)
        val request = server.takeRequest()
        assertEquals("/v1/sessions/abc/fields", request.url.encodedPath)
        val body = request.body!!.utf8()
        assertTrue(body.contains("name=\"file\"; filename=\"field.jpg\""))
        assertTrue(body.contains("Content-Type: image/jpeg"))
    }

    @Test
    fun reportCarriesTheLanguage() = runTest {
        reply(200, JOB_RUNNING)
        api().startReport("abc", "sw")
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("sw", request.url.queryParameter("language"))
    }

    @Test
    fun serverDetailBecomesTheError() = runTest {
        reply(422, """{"detail": "at most 60 fields per slide"}""")
        try {
            api().createSession()
            fail("expected an error")
        } catch (e: ApiException) {
            assertEquals("at most 60 fields per slide", e.message)
        }
    }

    @Test
    fun voiceUploadsAudioAndParsesTheCommand() = runTest {
        reply(200, """{"transcript": "note, pale stain", "action": "note", "note": "pale stain", "voice_notes": ["pale stain"]}""")
        val audio = kotlin.io.path.createTempFile(suffix = ".m4a").toFile().apply { writeBytes(byteArrayOf(1, 2, 3)) }
        val voice = api().sendVoice("abc", audio)
        val request = server.takeRequest()
        assertEquals("/v1/sessions/abc/voice", request.url.encodedPath)
        assertTrue(request.body!!.utf8().contains("Content-Type: audio/mp4"))
        assertEquals("note", voice.action)
        assertEquals("pale stain", voice.note)
        assertEquals(listOf("pale stain"), voice.voiceNotes)
        audio.delete()
    }

    @Test
    fun reportCarriesVoiceNotes() {
        val r = Parse.result(org.json.JSONObject("""{"slide": {}, "voice_notes": ["thick smear"]}"""))
        assertEquals(listOf("thick smear"), r.voiceNotes)
        assertEquals(emptyList<String>(), Parse.result(org.json.JSONObject("""{"slide": {}}""")).voiceNotes)
    }

    @Test
    fun health() = runTest {
        reply(200, """{"status": "ok", "version": "0.4.0", "segmenter": "hybrid"}""")
        assertTrue(api().health())
    }

    @Test
    fun addressesWithoutSchemeOrSlash() {
        assertEquals("http://192.168.1.20:8000/", DarubiniApi.normalise(" 192.168.1.20:8000 "))
        assertEquals("https://x.example/", DarubiniApi.normalise("https://x.example/"))
    }
}
