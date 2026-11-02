package app.darubini.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import app.darubini.R

/**
 * Design tokens from the "Credit Design" Figma system (01 · Foundations), adopted as
 * Darubini's own. Use a token, never a raw value.
 */
object Tokens {
    // Brand
    val Primary = Color(0xFF215732)
    val PrimaryStrong = Color(0xFF16391F)
    val PrimarySoft = Color(0xFFE8F3E3)
    val PrimarySofter = Color(0xFFEEF7EA)
    val PrimaryWash = Color(0xFFF6FAF4)
    val Lime = Color(0xFF43B02A)
    val LimeSoft = Color(0xFFDDF0D5)
    val LimeText = Color(0xFF2A6E1B)
    val LimeBright = Color(0xFF9BE36F)

    // Surface
    val Background = Color(0xFFECEEED)
    val Card = Color(0xFFFFFFFF)
    val Muted = Color(0xFFF4F6F5)
    val Muted2 = Color(0xFFEEF1EF)
    val Subtle = Color(0xFFFAFBFA)
    val Ink = Color(0xFF1C2420)

    // Text
    val Foreground = Color(0xFF151A17)
    val TextMuted = Color(0xFF6B736E)
    val TextFaint = Color(0xFF6E7671)
    val OnPrimary = Color(0xFFFFFFFF)
    val ForegroundSoft = Color(0xFF2F3832)

    // Border
    val Border = Color(0xFFE5E8E6)
    val BorderInput = Color(0xFFDDE2DF)
    val BorderStrong = Color(0xFFCFD8D3)
    val Ring = Color(0xFF3A9A24)

    // Status
    val Warning = Color(0xFFF0A33A)
    val WarningStrong = Color(0xFF9A5B07)
    val WarningSoft = Color(0xFFFDF2E1)
    val Danger = Color(0xFFC8412F)
    val DangerStrong = Color(0xFFA13322)
    val DangerSoft = Color(0xFFFBE9E6)
    val Info = Color(0xFF5B5BD6)
    val InfoStrong = Color(0xFF3E3EB0)
    val InfoSoft = Color(0xFFECECFB)
    val MarkFaint = Color(0xFF9AA29D)
}

/** Corner radii (radius/xs … radius/pill). */
object Radius {
    val Xs = 4.dp
    val Sm = 10.dp
    val R12 = 12.dp
    val Md = 14.dp
    val R16 = 16.dp
    val Card = 22.dp
    val Xl = 30.dp
}

/** Detection overlay colours, the same as the web app's --parasite and --wbc. */
object Marks {
    val Parasite = Color(0xFFD1006F)
    val Wbc = Color(0xFF1F6FD1)
}

private fun jakarta(weight: Int) = Font(
    R.font.plus_jakarta_sans,
    weight = FontWeight(weight),
    variationSettings = FontVariation.Settings(FontVariation.weight(weight)),
)

val PlusJakartaSans = FontFamily(jakarta(400), jakarta(500), jakarta(600), jakarta(700))

/** The Figma text styles, by their Figma names. */
object Type {
    private fun style(weight: Int, size: Float, line: Float, tracking: Float = 0f) = TextStyle(
        fontFamily = PlusJakartaSans,
        fontWeight = FontWeight(weight),
        fontSize = size.sp,
        lineHeight = line.sp,
        letterSpacing = (tracking / size).em,
    )

    val PageTitle = style(700, 28f, 33.6f, -0.9f)
    val Metric = style(700, 28f, 32.2f, -1.1f)
    val Title = style(700, 20f, 25f, -0.5f)
    val CardTitle = style(700, 17f, 22.1f, -0.4f)
    val Section = style(600, 14f, 19.6f)
    val BodyLarge = style(400, 16f, 24f)
    val Body = style(400, 14f, 21.7f)
    val BodyStrong = style(600, 14f, 21f)
    val Label = style(600, 13f, 18.2f)
    val LabelSmall = style(600, 12f, 16.2f)
    val BodySmall = style(400, 13f, 19.5f)
    val Caption = style(400, 12f, 16.8f)
    val Eyebrow = style(600, 11.5f, 14.95f, 0.6f)
}

private val Scheme = lightColorScheme(
    primary = Tokens.Primary,
    onPrimary = Tokens.OnPrimary,
    primaryContainer = Tokens.PrimarySoft,
    onPrimaryContainer = Tokens.PrimaryStrong,
    inversePrimary = Tokens.LimeBright,
    secondary = Tokens.Lime,
    onSecondary = Tokens.PrimaryStrong,
    secondaryContainer = Tokens.LimeSoft,
    onSecondaryContainer = Tokens.LimeText,
    tertiary = Tokens.Info,
    onTertiary = Tokens.OnPrimary,
    tertiaryContainer = Tokens.InfoSoft,
    onTertiaryContainer = Tokens.InfoStrong,
    error = Tokens.Danger,
    onError = Tokens.OnPrimary,
    errorContainer = Tokens.DangerSoft,
    onErrorContainer = Tokens.DangerStrong,
    background = Tokens.Muted,
    onBackground = Tokens.Foreground,
    surface = Tokens.Muted,
    onSurface = Tokens.Foreground,
    surfaceVariant = Tokens.Muted2,
    onSurfaceVariant = Tokens.TextMuted,
    outline = Tokens.BorderStrong,
    outlineVariant = Tokens.Border,
    inverseSurface = Tokens.Ink,
    inverseOnSurface = Tokens.OnPrimary,
    surfaceBright = Tokens.Card,
    surfaceDim = Tokens.Background,
    surfaceContainerLowest = Tokens.Card,
    surfaceContainerLow = Tokens.Card,
    surfaceContainer = Tokens.Card,
    surfaceContainerHigh = Tokens.Subtle,
    surfaceContainerHighest = Tokens.Muted2,
)

private val AppTypography = Typography(
    displaySmall = Type.PageTitle,
    headlineMedium = Type.PageTitle,
    headlineSmall = Type.Title,
    titleLarge = Type.Title,
    titleMedium = Type.CardTitle,
    titleSmall = Type.Section,
    bodyLarge = Type.BodyLarge,
    bodyMedium = Type.Body,
    bodySmall = Type.BodySmall,
    labelLarge = Type.Label,
    labelMedium = Type.LabelSmall,
    labelSmall = Type.Caption,
)

private val AppShapes = Shapes(
    extraSmall = RoundedCornerShape(Radius.Xs),
    small = RoundedCornerShape(Radius.Sm),
    medium = RoundedCornerShape(Radius.Md),
    large = RoundedCornerShape(Radius.Card),
    extraLarge = RoundedCornerShape(Radius.Xl),
)

/** The design system is light only; the camera screens use [Tokens.Ink] on their own. */
@Composable
fun DarubiniTheme(content: @Composable () -> Unit) {
    MaterialExpressiveTheme(
        colorScheme = Scheme,
        typography = AppTypography,
        shapes = AppShapes,
        motionScheme = MotionScheme.expressive(),
        content = content,
    )
}
