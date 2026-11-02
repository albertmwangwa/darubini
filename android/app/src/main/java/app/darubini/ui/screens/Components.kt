package app.darubini.ui.screens

import android.graphics.Bitmap
import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import app.darubini.R
import app.darubini.data.FieldReply
import app.darubini.ui.theme.Marks
import app.darubini.ui.theme.Radius
import app.darubini.ui.theme.Tokens
import app.darubini.ui.theme.Type
import kotlin.math.max

@Composable
fun Symbol(@DrawableRes id: Int, contentDescription: String? = null, modifier: Modifier = Modifier, tint: Color = Tokens.Foreground) {
    Icon(painterResource(id), contentDescription, modifier.size(20.dp), tint = tint)
}

/** Page header: back or close on the left, title and subtitle, actions on the right. */
@Composable
fun Header(
    title: String,
    subtitle: String? = null,
    @DrawableRes navIcon: Int? = null,
    navLabel: String? = null,
    onNav: () -> Unit = {},
    actions: @Composable RowScope.() -> Unit = {},
) {
    Row(
        Modifier.fillMaxWidth().padding(start = 8.dp, end = 16.dp, top = 12.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (navIcon != null) {
            Box(
                Modifier.size(44.dp).clip(CircleShape).clickable(onClick = onNav),
                contentAlignment = Alignment.Center,
            ) { Symbol(navIcon, navLabel, Modifier.size(24.dp)) }
            Spacer(Modifier.width(4.dp))
        } else {
            Spacer(Modifier.width(8.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = Type.Title, color = Tokens.Foreground, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) {
                Text(subtitle, style = Type.Caption, color = Tokens.TextMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically, content = actions)
    }
}

/** Round white icon button with a hairline border, as in the Figma headers. */
@Composable
fun CircleIconButton(@DrawableRes icon: Int, label: String?, onClick: () -> Unit, enabled: Boolean = true) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = CircleShape,
        color = Tokens.Card,
        border = BorderStroke(1.dp, Tokens.Border),
        modifier = Modifier.size(44.dp),
    ) {
        Box(contentAlignment = Alignment.Center) { Symbol(icon, label, Modifier.size(22.dp)) }
    }
}

enum class ButtonKind { Primary, Soft, Outline, Ghost, Danger, Lime }

enum class ButtonSize(val height: Dp, val padding: Dp) { L(52.dp, 24.dp), M(44.dp, 20.dp), S(36.dp, 14.dp) }

/** The Figma Button: pill shaped, six variants, three heights. */
@Composable
fun DsButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: ButtonKind = ButtonKind.Primary,
    size: ButtonSize = ButtonSize.L,
    @DrawableRes icon: Int? = null,
    enabled: Boolean = true,
    busy: Boolean = false,
) {
    val (container, content) = when (kind) {
        ButtonKind.Primary -> Tokens.Primary to Tokens.OnPrimary
        ButtonKind.Soft -> Tokens.PrimarySoft to Tokens.PrimaryStrong
        ButtonKind.Outline -> Tokens.Card to Tokens.Foreground
        ButtonKind.Ghost -> Color.Transparent to Tokens.Primary
        ButtonKind.Danger -> Tokens.Danger to Tokens.OnPrimary
        ButtonKind.Lime -> Tokens.Lime to Tokens.PrimaryStrong
    }
    val inner: @Composable RowScope.() -> Unit = {
        if (busy) {
            CircularProgressIndicator(Modifier.size(18.dp), color = content, strokeWidth = 2.dp)
            Spacer(Modifier.width(10.dp))
        } else if (icon != null) {
            Symbol(icon, tint = content)
            Spacer(Modifier.width(8.dp))
        }
        Text(text, style = if (size == ButtonSize.L) Type.BodyStrong else Type.Label, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
    val shape = RoundedCornerShape(percent = 50)
    val padding = PaddingValues(horizontal = size.padding)
    val sized = modifier.heightIn(min = size.height)
    when (kind) {
        ButtonKind.Outline -> OutlinedButton(
            onClick = onClick,
            enabled = enabled && !busy,
            shape = shape,
            border = BorderStroke(1.dp, Tokens.BorderStrong),
            colors = ButtonDefaults.outlinedButtonColors(containerColor = container, contentColor = content),
            contentPadding = padding,
            modifier = sized,
            content = inner,
        )
        ButtonKind.Ghost -> TextButton(
            onClick = onClick,
            enabled = enabled && !busy,
            shape = shape,
            colors = ButtonDefaults.textButtonColors(contentColor = content),
            contentPadding = padding,
            modifier = sized,
            content = inner,
        )
        else -> Button(
            onClick = onClick,
            enabled = enabled && !busy,
            shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = container,
                contentColor = content,
                disabledContainerColor = container.copy(alpha = 0.5f),
                disabledContentColor = content.copy(alpha = 0.8f),
            ),
            contentPadding = padding,
            modifier = sized,
            content = inner,
        )
    }
}

enum class Tone(val container: Color, val content: Color) {
    Success(Tokens.LimeSoft, Tokens.LimeText),
    Warning(Tokens.WarningSoft, Tokens.WarningStrong),
    Danger(Tokens.DangerSoft, Tokens.DangerStrong),
    Info(Tokens.InfoSoft, Tokens.InfoStrong),
    Neutral(Tokens.Muted2, Tokens.TextMuted),
    Offline(Tokens.Ink, Tokens.OnPrimary),
    Brand(Tokens.PrimarySoft, Tokens.PrimaryStrong),
}

/** Status is colour + word: a pill with an icon (or dot) and a label. */
@Composable
fun Badge(text: String, tone: Tone, @DrawableRes icon: Int? = null) {
    Row(
        Modifier.clip(RoundedCornerShape(percent = 50)).background(tone.container).padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(painterResource(icon), null, Modifier.size(14.dp), tint = tone.content)
        } else {
            Box(Modifier.size(6.dp).clip(CircleShape).background(tone.content))
        }
        Spacer(Modifier.width(6.dp))
        Text(text, style = Type.LabelSmall, color = tone.content, maxLines = 1)
    }
}

/** White card with the hairline border and the Elevation/Card shadow. */
@Composable
fun DsCard(
    modifier: Modifier = Modifier,
    radius: Dp = Radius.Card,
    color: Color = Tokens.Card,
    border: Color? = Tokens.Border,
    padding: Dp = 16.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(radius)
    Column(
        modifier
            .shadow(1.dp, shape, ambientColor = Tokens.Foreground.copy(alpha = 0.04f), spotColor = Tokens.Foreground.copy(alpha = 0.04f))
            .clip(shape)
            .background(color)
            .then(if (border != null) Modifier.border(1.dp, border, shape) else Modifier)
            .padding(padding),
        content = content,
    )
}

/** The Figma Metric tile: eyebrow, big number, caption. One per row is filled. */
@Composable
fun MetricTile(label: String, value: String, caption: String?, filled: Boolean, modifier: Modifier = Modifier) {
    DsCard(
        modifier,
        radius = Radius.R16,
        color = if (filled) Tokens.Primary else Tokens.Card,
        border = if (filled) null else Tokens.Border,
    ) {
        Text(label, style = Type.Caption, color = if (filled) Tokens.LimeBright else Tokens.TextMuted, maxLines = 1)
        Spacer(Modifier.height(6.dp))
        Text(value, style = Type.Metric, color = if (filled) Tokens.OnPrimary else Tokens.Foreground)
        if (caption != null) {
            Spacer(Modifier.height(6.dp))
            Text(caption, style = Type.LabelSmall, color = if (filled) Tokens.LimeBright else Tokens.LimeText, maxLines = 2)
        }
    }
}

/** The Figma Progress segment: equal steps, done ones in brand green, the current in lime. */
@Composable
fun ProgressSegments(done: Float, segments: Int = 10, modifier: Modifier = Modifier) {
    val full = (done * segments).toInt().coerceIn(0, segments)
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        repeat(segments) { i ->
            val color = when {
                i < full -> Tokens.Primary
                i == full && done > 0f && full < segments -> Tokens.Lime
                else -> Tokens.Muted2
            }
            Box(Modifier.weight(1f).height(6.dp).clip(RoundedCornerShape(percent = 50)).background(color))
        }
    }
}

/** The Figma Notice: a soft coloured panel with an icon, a title and a line of body. */
@Composable
fun Notice(
    title: String,
    body: String?,
    tone: Tone,
    @DrawableRes icon: Int,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(Radius.R16)).background(tone.container).padding(16.dp),
    ) {
        Icon(painterResource(icon), null, Modifier.size(22.dp), tint = tone.content)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = Type.BodyStrong, color = tone.content)
            if (!body.isNullOrBlank()) Text(body, style = Type.BodySmall, color = Tokens.ForegroundSoft)
            if (action != null) {
                Spacer(Modifier.height(8.dp))
                action()
            }
        }
    }
}

/** Section header: a label on the left and an optional action on the right. */
@Composable
fun SectionHeader(title: String, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Row(modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = Type.Section, color = Tokens.Foreground, modifier = Modifier.weight(1f))
        action?.invoke()
    }
}

/** The Figma Key value row: muted label left, strong value right, hairline below. */
@Composable
fun KeyValueRow(label: String, last: Boolean = false, value: @Composable () -> Unit) {
    Column {
        Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = Type.Body, color = Tokens.TextMuted, modifier = Modifier.weight(1f))
            value()
        }
        if (!last) Box(Modifier.fillMaxWidth().height(1.dp).background(Tokens.Border))
    }
}

@Composable
fun ValueText(text: String) = Text(text, style = Type.BodyStrong, color = Tokens.Foreground, textAlign = TextAlign.End)

/** The Figma Capture section: icon tile, title, subtitle and a status badge. */
@Composable
fun CaptureRow(
    @DrawableRes icon: Int,
    title: String,
    subtitle: String?,
    modifier: Modifier = Modifier,
    tone: Tone = Tone.Brand,
    badge: (@Composable () -> Unit)? = null,
) {
    DsCard(modifier.fillMaxWidth(), radius = Radius.R16, padding = 14.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(44.dp).clip(RoundedCornerShape(Radius.R12)).background(tone.container),
                contentAlignment = Alignment.Center,
            ) { Icon(painterResource(icon), null, Modifier.size(22.dp), tint = tone.content) }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = Type.BodyStrong, color = Tokens.Foreground)
                if (!subtitle.isNullOrBlank()) Text(subtitle, style = Type.BodySmall, color = Tokens.TextMuted)
            }
            if (badge != null) {
                Spacer(Modifier.width(8.dp))
                badge()
            }
        }
    }
}

/** The Figma Timeline item: a dot on a vertical line, a title and a detail line. */
@Composable
fun TimelineItem(title: String, detail: String?, last: Boolean, tone: Tone = Tone.Brand) {
    val dot = if (tone == Tone.Danger) Tokens.Danger else Tokens.Primary
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Column(Modifier.width(20.dp).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(5.dp))
            Box(Modifier.size(12.dp).clip(CircleShape).background(dot))
            if (!last) Box(Modifier.width(2.dp).weight(1f).background(Tokens.PrimarySoft))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f).padding(bottom = if (last) 0.dp else 16.dp)) {
            Text(title, style = Type.BodyStrong, color = Tokens.Foreground)
            if (!detail.isNullOrBlank()) Text(detail, style = Type.BodySmall, color = if (tone == Tone.Danger) Tokens.DangerStrong else Tokens.TextMuted)
        }
    }
}

/** The Figma Copilot chat bubble: a white card labelled with the sparkle. */
@Composable
fun CopilotCard(label: String, text: String, modifier: Modifier = Modifier) {
    DsCard(modifier.fillMaxWidth(), radius = Radius.R16) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(painterResource(R.drawable.ic_auto_awesome), null, Modifier.size(16.dp), tint = Tokens.Primary)
            Spacer(Modifier.width(6.dp))
            Text(label, style = Type.LabelSmall, color = Tokens.Primary)
        }
        Spacer(Modifier.height(8.dp))
        Text(text, style = Type.Body, color = Tokens.Foreground)
    }
}

/** The Figma Bottom action bar: white, a hairline on top, one or two buttons. */
@Composable
fun BottomActionBar(content: @Composable RowScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().background(Tokens.Card)) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Tokens.Border))
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            content = content,
        )
    }
}

/** A round soft-green tile holding an icon (hero marks, avatars). */
@Composable
fun IconDisc(@DrawableRes icon: Int, size: Dp, tone: Tone = Tone.Brand) {
    Box(Modifier.size(size).clip(CircleShape).background(tone.container), contentAlignment = Alignment.Center) {
        Icon(painterResource(icon), null, Modifier.size(size * 0.45f), tint = tone.content)
    }
}

@Composable
fun Disclaimer(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = Type.Caption,
        color = Tokens.TextMuted,
        textAlign = TextAlign.Center,
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

/** The uploaded field with parasites circled and white blood cells boxed, as in the web app. */
@Composable
fun FieldOverlay(image: Bitmap, field: FieldReply, modifier: Modifier = Modifier) {
    val bitmap = remember(image) { image.asImageBitmap() }
    Canvas(modifier.fillMaxWidth().aspectRatio(image.width.toFloat() / image.height)) {
        drawImage(bitmap, dstOffset = IntOffset.Zero, dstSize = IntSize(size.width.toInt(), size.height.toInt()))
        val sx = size.width / max(1, field.width)
        val sy = size.height / max(1, field.height)
        val line = max(2f, size.width / 300f)
        for (d in field.detections) {
            if (d.isParasite) {
                val r = max(6 * line, (d.x1 - d.x0) * sx)
                drawCircle(Marks.Parasite, r, Offset((d.x0 + d.x1) / 2 * sx, (d.y0 + d.y1) / 2 * sy), style = Stroke(line))
            } else {
                drawRect(Marks.Wbc, Offset(d.x0 * sx, d.y0 * sy), Size((d.x1 - d.x0) * sx, (d.y1 - d.y0) * sy), style = Stroke(line))
            }
        }
    }
}
