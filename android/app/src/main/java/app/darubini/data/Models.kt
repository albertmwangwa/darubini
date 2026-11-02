package app.darubini.data

import org.json.JSONArray
import org.json.JSONObject

/** The running slide count the server returns after every capture. */
data class Running(
    val parasites: Int,
    val wbcs: Int,
    val usableFields: Int,
    val wbcTarget: Int,
    val status: String,
    val densityPerUl: Int?,
    val reason: String,
) {
    /** Share of the white blood cell target counted so far, 0..1. */
    val progress: Float get() = if (wbcTarget <= 0) 0f else (wbcs.toFloat() / wbcTarget).coerceIn(0f, 1f)
}

/** One detection in field pixel coordinates. */
data class Detection(val cls: String, val x0: Float, val y0: Float, val x1: Float, val y1: Float) {
    val isParasite: Boolean get() = cls == "parasite"
}

data class FieldReply(
    val fieldId: String,
    val kept: Boolean,
    val flags: List<String>,
    val parasites: Int,
    val wbcs: Int,
    val width: Int,
    val height: Int,
    val detections: List<Detection>,
    /** The blocking problems in each language ("en", "sw"), as the server words them for the retake prompt. */
    val blockingText: Map<String, List<String>> = emptyMap(),
) {
    /** Quality problems that stopped the field being counted, in [language] when the server sent it. */
    fun blocking(language: String): List<String> =
        blockingText[language] ?: flags.filter { it.startsWith("blocking:") }.map { it.removePrefix("blocking:").trim() }
}

data class ClipReply(
    val fieldId: String,
    val frames: Int,
    val keyframes: Int,
    val tracker: String,
    val parasites: Int,
    val wbcs: Int,
    val naiveParasites: Int,
    val naiveWbcs: Int,
)

/** What the technician should do after a capture: "retake", "next" or "finish". */
data class Next(val action: String, val reason: String)

data class CaptureReply(val field: FieldReply?, val clip: ClipReply?, val running: Running, val next: Next)

data class SessionStart(val sessionId: String, val running: Running, val agent: Boolean)

/** One tool call the Muse Spark agent made, with a short language-neutral detail line. */
data class AgentStep(val tool: String, val detail: String, val failed: Boolean)

data class Audit(val sampled: Int, val confirmed: Int, val confirmedPercent: Int, val auditedParasites: Int, val flagged: Boolean)

data class SlideFacts(
    val fieldsExamined: Int,
    val usableFields: Int,
    val parasites: Int,
    val wbcs: Int,
    val densityPerUl: Int?,
    val status: String,
)

data class ReportResult(
    val language: String,
    val report: String,
    val narrative: String?,
    val audit: Audit?,
    val auditText: String?,
    val excluded: Map<String, String>,
    val slide: SlideFacts,
    val finishedByAgent: Boolean,
    val notes: List<String>,
    val text: String,
)

data class ReportJob(val state: String, val steps: List<AgentStep>, val result: ReportResult?, val error: String?) {
    val running: Boolean get() = state == "running"
}

/** Parsers for the server's JSON replies (see src/darubini/api/sessions.py). */
object Parse {
    fun running(o: JSONObject) = Running(
        parasites = o.optInt("parasites"),
        wbcs = o.optInt("wbcs"),
        usableFields = o.optInt("usable_fields"),
        wbcTarget = o.optInt("wbc_target", 200),
        status = o.optString("status"),
        densityPerUl = o.optIntOrNull("density_per_ul"),
        reason = o.optString("reason"),
    )

    fun session(o: JSONObject) = SessionStart(o.getString("session_id"), running(o.getJSONObject("running")), o.optBoolean("agent"))

    fun capture(o: JSONObject) = CaptureReply(
        field = o.optJSONObject("field")?.let(::field),
        clip = o.optJSONObject("clip")?.let(::clip),
        running = running(o.getJSONObject("running")),
        next = o.getJSONObject("next").let { Next(it.getString("action"), it.optString("reason")) },
    )

    fun field(o: JSONObject) = FieldReply(
        fieldId = o.getString("field_id"),
        kept = o.optBoolean("kept"),
        flags = o.optJSONArray("flags").strings(),
        parasites = o.optInt("parasites"),
        wbcs = o.optInt("wbcs"),
        width = o.optInt("width"),
        height = o.optInt("height"),
        detections = o.optJSONArray("detections").objects().map { d ->
            val b = d.getJSONArray("box")
            Detection(
                d.getString("class"),
                b.getDouble(0).toFloat(),
                b.getDouble(1).toFloat(),
                b.getDouble(2).toFloat(),
                b.getDouble(3).toFloat(),
            )
        },
        blockingText = o.optJSONObject("blocking_text")?.let { t ->
            t.keys().asSequence().associateWith { t.optJSONArray(it).strings() }
        } ?: emptyMap(),
    )

    fun clip(o: JSONObject) = ClipReply(
        fieldId = o.getString("field_id"),
        frames = o.optInt("frames"),
        keyframes = o.optInt("keyframes"),
        tracker = o.optString("tracker"),
        parasites = o.optInt("parasites"),
        wbcs = o.optInt("wbcs"),
        naiveParasites = o.optInt("naive_parasites"),
        naiveWbcs = o.optInt("naive_wbcs"),
    )

    fun job(o: JSONObject) = ReportJob(
        state = o.getString("state"),
        steps = o.optJSONArray("steps").objects().map(::step),
        result = o.optJSONObject("result")?.let(::result),
        error = o.optStringOrNull("error"),
    )

    /** Mirrors stepLine() in the web app: the detail is numbers and field ids, so it needs no translation. */
    fun step(o: JSONObject): AgentStep {
        val tool = o.getString("tool")
        val args = o.optJSONObject("arguments") ?: JSONObject()
        val r = o.optJSONObject("result") ?: JSONObject()
        val error = r.optStringOrNull("error")
        val detail = when {
            error != null -> error
            tool == "examine_next_fields" && r.has("running") -> {
                val run = r.getJSONObject("running")
                "${r.optInt("examined")} → ${run.optInt("parasites")} / ${run.optInt("wbcs")}"
            }
            tool == "review_field" -> {
                val verdict = if (r.optBoolean("usable")) "OK" else "✗"
                "${args.optString("field_id")}: $verdict ${r.optJSONArray("issues").strings().joinToString(", ")}".trim()
            }
            tool == "exclude_field" -> "${args.optString("field_id")}: ${args.optString("reason")}"
            tool == "audit_parasites" -> "${r.optInt("confirmed")} / ${r.optInt("sampled")}"
            else -> ""
        }
        return AgentStep(tool, detail, error != null)
    }

    fun result(o: JSONObject): ReportResult {
        val slide = o.optJSONObject("slide") ?: JSONObject()
        val excluded = o.optJSONObject("excluded")
        return ReportResult(
            language = o.optString("language", "en"),
            report = o.optString("report"),
            narrative = o.optStringOrNull("narrative")?.trim()?.takeIf { it.isNotEmpty() },
            audit = o.optJSONObject("audit")?.let {
                Audit(
                    sampled = it.optInt("sampled"),
                    confirmed = it.optInt("confirmed"),
                    confirmedPercent = it.optInt("confirmed_percent"),
                    auditedParasites = it.optInt("audited_parasites"),
                    flagged = it.optBoolean("flagged"),
                )
            },
            auditText = o.optStringOrNull("audit_text"),
            excluded = excluded?.keys()?.asSequence()?.associateWith { excluded.getString(it) } ?: emptyMap(),
            slide = SlideFacts(
                fieldsExamined = slide.optInt("fields_examined"),
                usableFields = slide.optInt("usable_fields"),
                parasites = slide.optInt("parasites"),
                wbcs = slide.optInt("wbcs"),
                densityPerUl = slide.optIntOrNull("density_per_ul"),
                status = slide.optString("status"),
            ),
            finishedByAgent = o.optBoolean("finished_by_agent"),
            notes = o.optJSONArray("notes").strings(),
            text = o.optString("text"),
        )
    }

    private fun JSONObject.optStringOrNull(key: String): String? = if (isNull(key)) null else optString(key)

    private fun JSONObject.optIntOrNull(key: String): Int? = if (isNull(key)) null else Math.round(optDouble(key)).toInt()

    private fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else List(length()) { getString(it) }

    private fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else List(length()) { getJSONObject(it) }
}
