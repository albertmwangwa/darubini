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
 * Design tokens. Colours follow the Darubini Proposal palette (docs/proposal/index.html):
 * blue primary, slate neutrals, stain purple for info, green for success. Type, radii and
 * components follow the "Credit Design" Figma system. Token names are kept from that
 * system ("Lime" is the success/accent role). Use a token, never a raw value.
 */
object Tokens {
    // Brand
    val Primary = Color(0xFF2463EB)
    val PrimaryStrong = Color(0xFF1842B4)
    val PrimarySoft = Color(0xFFECF1FE)
    val PrimarySofter = Color(0xFFF2F6FE)
    val PrimaryWash = Color(0xFFF7F9FE)
    val Lime = Color(0xFF25935F)
    val LimeSoft = Color(0xFFE3F3EA)
    val LimeText = Color(0xFF1D7A4E)
    val LimeBright = Color(0xFF90C7FE)

    // Surface
    val Background = Color(0xFFE9ECF1)
    val Card = Color(0xFFFFFFFF)
    val Muted = Color(0xFFF3F4F7)
    val Muted2 = Color(0xFFEDEFF3)
    val Subtle = Color(0xFFFAFBFC)
    val Ink = Color(0xFF0F1729)

    // Text
    val Foreground = Color(0xFF0F1729)
    val TextMuted = Color(0xFF5D6779)
    val TextFaint = Color(0xFF6B7486)
    val OnPrimary = Color(0xFFFFFFFF)
    val ForegroundSoft = Color(0xFF273041)

    // Border
    val Border = Color(0xFFDEE1E7)
    val BorderInput = Color(0xFFD5D9E0)
    val BorderStrong = Color(0xFFC8CED8)
    val Ring = Color(0xFF2463EB)

    // Status
    val Warning = Color(0xFFE08A1E)
    val WarningStrong = Color(0xFFA3580A)
    val WarningSoft = Color(0xFFFDF3E2)
    val Danger = Color(0xFFDC2626)
    val DangerStrong = Color(0xFFB91C1C)
    val DangerSoft = Color(0xFFFEECEC)
    val Info = Color(0xFF683B9B)
    val InfoStrong = Color(0xFF522E7B)
    val InfoSoft = Color(0xFFF1EAF8)
    val MarkFaint = Color(0xFFA0A7B4)
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
    val Parasite = Color(0xFFDB2777)
    val Wbc = Color(0xFF2463EB)
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
