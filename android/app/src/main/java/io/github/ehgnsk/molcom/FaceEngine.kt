package io.github.ehgnsk.molcom

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import org.opencv.android.OpenCVLoader
import org.opencv.android.Utils
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.Size
import org.opencv.imgproc.Imgproc
import org.opencv.objdetect.FaceDetectorYN
import org.opencv.objdetect.FaceRecognizerSF
import java.io.File
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

class Face(val area: Float, val vector: FloatArray)

/** YuNet 얼굴 검출과 SFace 얼굴 특징 추출. 한 스레드에서만 써야 한다. */
class FaceEngine(context: Context) {
    private val detector: FaceDetectorYN
    private val recognizer: FaceRecognizerSF
    private var inputSize = Size(0.0, 0.0)

    init {
        check(OpenCVLoader.initLocal()) { "OpenCV를 불러오지 못했습니다." }
        detector = FaceDetectorYN.create(
            modelPath(context, DETECT_MODEL), "", Size(320.0, 240.0), 0.7f, 0.3f, 50
        )
        recognizer = FaceRecognizerSF.create(modelPath(context, RECOG_MODEL), "")
    }

    /** BGR 영상에서 찾은 얼굴마다 크기와 특징 벡터(길이 1)를 돌려준다. */
    fun faces(bgr: Mat): List<Face> {
        val scale = min(1.0, DETECT_SIZE / max(bgr.cols(), bgr.rows()).toDouble())
        val small = if (scale < 1.0) {
            Mat().also { Imgproc.resize(bgr, it, Size(), scale, scale, Imgproc.INTER_AREA) }
        } else {
            bgr
        }
        val size = Size(small.cols().toDouble(), small.rows().toDouble())
        if (size != inputSize) {
            detector.setInputSize(size)
            inputSize = size
        }
        val found = Mat()
        detector.detect(small, found)

        val result = ArrayList<Face>()
        val row = FloatArray(15)
        for (i in 0 until found.rows()) {
            found.get(i, 0, row)
            // 검출은 줄인 영상에서 했으므로 좌표를 원본 기준으로 되돌린다.
            for (k in 0 until 14) row[k] = (row[k] / scale).toFloat()
            val box = Mat(1, 15, CvType.CV_32F)
            box.put(0, 0, row)
            val aligned = Mat()
            val feature = Mat()
            recognizer.alignCrop(bgr, box, aligned)
            recognizer.feature(aligned, feature)
            val vector = FloatArray(feature.total().toInt())
            feature.get(0, 0, vector)
            var norm = 0f
            for (value in vector) norm += value * value
            norm = sqrt(norm)
            if (norm > 0f) for (k in vector.indices) vector[k] /= norm
            result.add(Face(row[2] * row[3], vector))
            box.release()
            aligned.release()
            feature.release()
        }
        found.release()
        if (small !== bgr) small.release()
        return result
    }

    /** 사진에서 가장 큰 얼굴의 특징 벡터. 얼굴이 없으면 null. */
    fun largestFace(context: Context, uri: Uri): FloatArray? {
        val bitmap = loadBitmap(context, uri) ?: return null
        val rgba = Mat()
        Utils.bitmapToMat(bitmap, rgba)
        val bgr = Mat()
        Imgproc.cvtColor(rgba, bgr, Imgproc.COLOR_RGBA2BGR)
        val best = faces(bgr).maxByOrNull { it.area }
        rgba.release()
        bgr.release()
        bitmap.recycle()
        return best?.vector
    }

    companion object {
        private const val DETECT_MODEL = "face_detection_yunet_2023mar.onnx"
        private const val RECOG_MODEL = "face_recognition_sface_2021dec.onnx"
        private const val DETECT_SIZE = 640.0
        private const val PHOTO_SIZE = 1600

        /** OpenCV는 파일 경로로 모델을 읽으므로 assets의 모델을 내부 저장소로 복사한다. */
        private fun modelPath(context: Context, name: String): String {
            val file = File(context.filesDir, name)
            val expected = context.assets.openFd(name).use { it.length }
            if (!file.exists() || file.length() != expected) {
                context.assets.open(name).use { input ->
                    file.outputStream().use { output -> input.copyTo(output) }
                }
            }
            return file.absolutePath
        }

        /** 사진을 적당한 크기로 읽고, 촬영 방향(EXIF)에 맞게 돌려 놓는다. */
        private fun loadBitmap(context: Context, uri: Uri): Bitmap? {
            val resolver = context.contentResolver
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
            var sample = 1
            while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= PHOTO_SIZE) sample *= 2
            val options = BitmapFactory.Options().apply {
                inSampleSize = sample
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }
            val bitmap = resolver.openInputStream(uri)?.use {
                BitmapFactory.decodeStream(it, null, options)
            } ?: return null

            val orientation = resolver.openInputStream(uri)?.use {
                ExifInterface(it).getAttributeInt(
                    ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL
                )
            } ?: ExifInterface.ORIENTATION_NORMAL
            val degrees = when (orientation) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
            if (degrees == 0f) return bitmap
            val matrix = Matrix().apply { postRotate(degrees) }
            val rotated = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
            if (rotated !== bitmap) bitmap.recycle()
            return rotated
        }
    }
}
