package app.darubini.ui.screens

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import app.darubini.R
import app.darubini.data.Next
import app.darubini.ui.Strings
import app.darubini.ui.UiState
import app.darubini.ui.theme.Radius
import app.darubini.ui.theme.Tokens
import app.darubini.ui.theme.Type
import java.io.File

/** Records video into EXTRA_OUTPUT with a duration cap; the server reads at most 60 frames. */
private class RecordPan : ActivityResultContract<Uri, Boolean>() {
    override fun createIntent(context: Context, input: Uri): Intent =
        Intent(MediaStore.ACTION_VIDEO_CAPTURE)
            .putExtra(MediaStore.EXTRA_OUTPUT, input)
            .putExtra(MediaStore.EXTRA_DURATION_LIMIT, 8)
            .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)

    override fun parseResult(resultCode: Int, intent: Intent?): Boolean = resultCode == Activity.RESULT_OK
}

private fun captureFile(context: Context, name: String): Pair<File, Uri> {
    val file = File(File(context.cacheDir, "captures").apply { mkdirs() }, name)
    return file to FileProvider.getUriForFile(context, "${context.packageName}.files", file)
}

@Composable
fun CaptureScreen(
    state: UiState,
    padding: PaddingValues,
    onBack: () -> Unit,
    onPhoto: (Uri) -> Unit,
    onClip: (File) -> Unit,
    onPickedVideo: (Uri) -> Unit,
    onFinish: () -> Unit,
    onMessage: (String) -> Unit,
) {
    val s = state.strings
    val context = LocalContext.current
    var photoPath by rememberSaveable { mutableStateOf<String?>(null) }
    var clipPath by rememberSaveable { mutableStateOf<String?>(null) }

    val takePhoto = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val path = photoPath
        if (ok && path != null) onPhoto(Uri.fromFile(File(path)))
    }
    val recordPan = rememberLauncherForActivityResult(RecordPan()) { ok ->
        val path = clipPath
        if (ok && path != null && File(path).length() > 0) onClip(File(path))
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) {
            val type = context.contentResolver.getType(uri).orEmpty()
            if (type.startsWith("video/")) onPickedVideo(uri) else onPhoto(uri)
        }
    }
    val launchSafely: (() -> Unit) -> Unit = { launch ->
        try {
            launch()
        } catch (_: ActivityNotFoundException) {
            onMessage(s.noCamera)
        }
    }
    val photo = {
        val (file, uri) = captureFile(context, "field.jpg")
        photoPath = file.path
        launchSafely { takePhoto.launch(uri) }
    }
    val pan = {
        val (file, uri) = captureFile(context, "pan.mp4")
        file.delete()
        clipPath = file.path
        launchSafely { recordPan.launch(uri) }
    }
    val r = state.running
    val done = state.next?.action == "finish"

    Column(Modifier.fillMaxSize().padding(padding)) {
        Header(
            s.slide,
            r?.let { s.slideSub(it.usableFields, it.wbcTarget) },
            R.drawable.ic_arrow_back,
            s.back,
            onBack,
        ) {
            CircleIconButton(R.drawable.ic_photo_library, s.gallery, {
                pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo))
            }, enabled = !state.busy)
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (r != null) {
                Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    MetricTile(
                        s.parasites,
                        s.number(r.parasites),
                        r.densityPerUl?.let { "${s.number(it)} ${s.perUl}" },
                        filled = true,
                        modifier = Modifier.weight(1f).fillMaxHeight(),
                    )
                    MetricTile(
                        s.wbcs,
                        s.number(r.wbcs),
                        s.ofTarget(r.wbcTarget),
                        filled = false,
                        modifier = Modifier.weight(1f).fillMaxHeight(),
                    )
                }
                DsCard(Modifier.fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(s.target(r.wbcs, r.wbcTarget), style = Type.BodyStrong, color = Tokens.Foreground, modifier = Modifier.weight(1f))
                        if (done) Badge(s.complete, Tone.Success, R.drawable.ic_check_circle) else Badge(s.inProgress, Tone.Warning, R.drawable.ic_schedule)
                    }
                    Spacer(Modifier.height(12.dp))
                    ProgressSegments(r.progress)
                }
            }
            state.next?.let { NextNotice(it, state, s) }
            LastCapture(state)
        }
        if (!done && state.fieldsKept > 0) {
            DsButton(
                s.finish,
                onFinish,
                Modifier.fillMaxWidth(),
                ButtonKind.Ghost,
                ButtonSize.S,
                icon = R.drawable.ic_task_alt,
                enabled = !state.busy,
            )
        }
        BottomActionBar {
            if (done) {
                DsButton(s.photoButton, photo, Modifier.weight(1f), ButtonKind.Outline, icon = R.drawable.ic_photo_camera, enabled = !state.busy)
                DsButton(s.finish, onFinish, Modifier.weight(1f), icon = R.drawable.ic_task_alt, enabled = !state.busy)
            } else {
                DsButton(s.clipButton, pan, Modifier.weight(1f), ButtonKind.Outline, icon = R.drawable.ic_videocam, enabled = !state.busy)
                DsButton(
                    if (state.busy) s.analysing else s.photoButton,
                    photo,
                    Modifier.weight(1f),
                    icon = R.drawable.ic_photo_camera,
                    busy = state.busy,
                )
            }
        }
    }
}

@Composable
private fun NextNotice(next: Next, state: UiState, s: Strings) {
    val r = state.running
    when (next.action) {
        "retake" -> Notice(
            s.retake(state.lastField?.blocking(state.language)?.joinToString("; ")?.ifEmpty { null } ?: s.quality),
            null,
            Tone.Danger,
            R.drawable.ic_refresh,
        )
        "finish" -> Notice(s.done, null, Tone.Success, R.drawable.ic_check_circle)
        else -> Notice(s.next, r?.let { s.target(it.wbcs, it.wbcTarget) }, Tone.Brand, R.drawable.ic_arrow_forward)
    }
}

@Composable
private fun LastCapture(state: UiState) {
    val s = state.strings
    val field = state.lastField
    val image = state.lastImage
    val clip = state.lastClip
    if (field != null && image != null) {
        DsCard(Modifier.fillMaxWidth(), padding = 12.dp) {
            FieldOverlay(image, field, Modifier.clip(RoundedCornerShape(Radius.R12)))
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    s.fieldLine(field.parasites, field.wbcs),
                    style = Type.BodySmall,
                    color = Tokens.ForegroundSoft,
                    modifier = Modifier.weight(1f),
                )
                if (field.kept) Badge(s.counted, Tone.Success, R.drawable.ic_check_circle) else Badge(s.notCounted, Tone.Danger, R.drawable.ic_block)
            }
        }
    } else if (clip != null) {
        CaptureRow(R.drawable.ic_videocam, s.clip, s.clipLine(clip), badge = { Badge(s.counted, Tone.Success, R.drawable.ic_check_circle) })
    }
}
