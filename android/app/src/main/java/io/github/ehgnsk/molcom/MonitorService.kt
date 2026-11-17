package io.github.ehgnsk.molcom

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.SystemClock
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import org.opencv.core.Core
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.imgproc.Imgproc
import java.util.concurrent.Executors

/** 화면이 꺼져 있지 않은 동안 전면 카메라를 보며 등록된 사람이 보이면 앱을 전환한다. */
class MonitorService : LifecycleService() {
    private val executor = Executors.newSingleThreadExecutor()
    private var engine: FaceEngine? = null
    private var started = false
    private var lastLaunch = 0L
    private var lastNames = ""

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        try {
            val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
            } else {
                0
            }
            ServiceCompat.startForeground(this, NOTIFICATION_ID, notification(), type)
        } catch (e: Exception) {
            fail("감시를 시작하지 못했습니다: " + e.message)
            return START_NOT_STICKY
        }
        if (!started) {
            started = true
            Store.load(this)
            MonitorState.error.value = ""
            MonitorState.detected.value = ""
            MonitorState.running.value = true
            startCamera()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        executor.shutdown()
        MonitorState.running.value = false
        MonitorState.detected.value = ""
        super.onDestroy()
    }

    private fun fail(message: String) {
        MonitorState.error.postValue(message)
        stopSelf()
    }

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            try {
                val provider = future.get()
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()
                analysis.setAnalyzer(executor) { image -> analyze(image) }
                val selector = if (provider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA)) {
                    CameraSelector.DEFAULT_FRONT_CAMERA
                } else {
                    CameraSelector.DEFAULT_BACK_CAMERA
                }
                provider.unbindAll()
                provider.bindToLifecycle(this, selector, analysis)
            } catch (e: Exception) {
                fail("카메라를 열 수 없습니다: " + e.message)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyze(image: ImageProxy) {
        try {
            val current = engine ?: FaceEngine(applicationContext).also { engine = it }
            val plane = image.planes[0]
            val rgba = Mat(
                image.height, image.width, CvType.CV_8UC4, plane.buffer, plane.rowStride.toLong()
            )
            val bgr = Mat()
            Imgproc.cvtColor(rgba, bgr, Imgproc.COLOR_RGBA2BGR)
            val upright = when (image.imageInfo.rotationDegrees) {
                90 -> Mat().also { Core.rotate(bgr, it, Core.ROTATE_90_CLOCKWISE) }
                180 -> Mat().also { Core.rotate(bgr, it, Core.ROTATE_180) }
                270 -> Mat().also { Core.rotate(bgr, it, Core.ROTATE_90_COUNTERCLOCKWISE) }
                else -> bgr
            }
            val names = current.faces(upright).mapNotNull { Store.match(it.vector) }
                .distinct().sorted().joinToString(", ")
            if (upright !== bgr) upright.release()
            bgr.release()
            rgba.release()

            // 등록된 사람이 보이는 동안에는 1초마다 대상 앱을 다시 앞으로 가져온다.
            if (names.isNotEmpty()) {
                val now = SystemClock.elapsedRealtime()
                if (now - lastLaunch >= RELAUNCH_MS) {
                    lastLaunch = now
                    launchTarget(this)
                }
            }
            if (names != lastNames) {
                lastNames = names
                MonitorState.detected.postValue(names)
            }
        } catch (e: Throwable) {
            Log.e("MolCom", "analyze failed", e)
            fail("얼굴 인식 중 오류가 발생했습니다: " + e.message)
        } finally {
            image.close()
        }
    }

    private fun notification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "감시 상태", NotificationManager.IMPORTANCE_LOW)
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, MonitorService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("MolCom 감시 중")
            .setContentText("등록된 사람이 보이면 앱을 전환합니다.")
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(0, "감시 중지", stop)
            .build()
    }

    companion object {
        const val ACTION_STOP = "io.github.ehgnsk.molcom.STOP"
        private const val CHANNEL = "monitor"
        private const val NOTIFICATION_ID = 1
        private const val RELAUNCH_MS = 1000L

        /** 전환할 앱을 화면 맨 앞으로 가져온다. 성공하면 true. */
        fun launchTarget(context: Context): Boolean {
            val target = Store.targetPackage(context)
            if (target.isEmpty()) return false
            val intent = context.packageManager.getLaunchIntentForPackage(target) ?: return false
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            return try {
                context.startActivity(intent)
                true
            } catch (e: Exception) {
                false
            }
        }
    }
}
