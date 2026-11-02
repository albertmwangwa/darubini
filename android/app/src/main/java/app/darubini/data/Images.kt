package app.darubini.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import kotlin.math.max

/** Same limits as the web app: fields go up at 2048 px as JPEG 85. */
object Images {
    const val UPLOAD_SIDE = 2048
    const val JPEG_QUALITY = 85

    /** The server refuses clips over 60 MB. */
    const val MAX_CLIP_BYTES = 60L * 1024 * 1024

    /** Decode a photo upright and no larger than [maxSide] on its long side. */
    fun loadDownscaled(context: Context, uri: Uri, maxSide: Int = UPLOAD_SIDE): Bitmap {
        val resolver = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0) throw IOException("not an image")

        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
        val decoded = resolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: throw IOException("not an image")

        val rotation = resolver.openInputStream(uri)?.use { ExifInterface(it).rotationDegrees } ?: 0
        val scale = minOf(1f, maxSide.toFloat() / max(decoded.width, decoded.height))
        if (rotation == 0 && scale == 1f) return decoded
        val matrix = Matrix().apply {
            postScale(scale, scale)
            postRotate(rotation.toFloat())
        }
        return Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
    }

    fun jpeg(bitmap: Bitmap, quality: Int = JPEG_QUALITY): ByteArray =
        ByteArrayOutputStream().use { out ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
            out.toByteArray()
        }

    /** Copy a picked video into the cache so it can be uploaded as a file. */
    fun copyToCache(context: Context, uri: Uri, name: String): File {
        val dir = File(context.cacheDir, "captures").apply { mkdirs() }
        val target = File(dir, name)
        context.contentResolver.openInputStream(uri)?.use { input ->
            target.outputStream().use { input.copyTo(it) }
        } ?: throw IOException("could not read the video")
        return target
    }
}
