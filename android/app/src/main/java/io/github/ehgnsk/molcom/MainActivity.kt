package io.github.ehgnsk.molcom

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import java.io.File
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private var engine: FaceEngine? = null      // worker 스레드에서만 쓴다.
    private var captureUri: Uri? = null
    private var afterCamera: (() -> Unit)? = null
    private var askedNotifications = false

    private lateinit var statusTitle: TextView
    private lateinit var statusHint: TextView
    private lateinit var toggle: MaterialButton
    private lateinit var peopleList: LinearLayout
    private lateinit var targetName: TextView
    private lateinit var testSwitch: MaterialButton

    private val pickPhotos =
        registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
            if (uris.isNotEmpty()) registerFrom(uris)
        }

    private val takePhoto =
        registerForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
            val uri = captureUri
            if (saved && uri != null) registerFrom(listOf(uri))
        }

    private val askCamera =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            val next = afterCamera
            afterCamera = null
            if (granted) {
                next?.invoke()
            } else {
                toast("카메라 권한이 없으면 사용할 수 없습니다.")
            }
        }

    private val askNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { start() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        Store.load(this)

        statusTitle = findViewById(R.id.statusTitle)
        statusHint = findViewById(R.id.statusHint)
        toggle = findViewById(R.id.toggle)
        peopleList = findViewById(R.id.peopleList)
        targetName = findViewById(R.id.targetName)
        testSwitch = findViewById(R.id.testSwitch)

        toggle.setOnClickListener {
            if (MonitorState.running.value == true) stop() else start()
        }
        findViewById<MaterialButton>(R.id.addCamera).setOnClickListener { withCamera { capture() } }
        findViewById<MaterialButton>(R.id.addPhoto).setOnClickListener { pickPhotos.launch("image/*") }
        findViewById<MaterialButton>(R.id.chooseApp).setOnClickListener { chooseApp() }
        testSwitch.setOnClickListener {
            if (!MonitorService.launchTarget(this)) toast("앱을 열 수 없습니다. 다시 선택하십시오.")
        }

        val group = findViewById<MaterialButtonToggleGroup>(R.id.sensitivity)
        group.check(
            when (Store.sensitivity(this)) {
                "low" -> R.id.sensLow
                "high" -> R.id.sensHigh
                else -> R.id.sensNormal
            }
        )
        group.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (isChecked) {
                Store.setSensitivity(
                    this,
                    when (checkedId) {
                        R.id.sensLow -> "low"
                        R.id.sensHigh -> "high"
                        else -> "normal"
                    }
                )
            }
        }

        MonitorState.running.observe(this) { render() }
        MonitorState.detected.observe(this) { render() }
        MonitorState.error.observe(this) { message ->
            if (message.isNotEmpty()) {
                MonitorState.error.value = ""
                MaterialAlertDialogBuilder(this).setMessage(message)
                    .setPositiveButton(android.R.string.ok, null).show()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }

    // ---- 상태 표시 ----

    private fun targetLabel(): String {
        val target = Store.targetPackage(this)
        if (target.isEmpty()) return ""
        return try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(target, 0)).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            ""
        }
    }

    /** 감시를 시작할 수 없는 이유. 문제가 없으면 null. */
    private fun problem(label: String): String? = when {
        Store.people.isEmpty() -> "1단계에서 감지할 사람을 등록하십시오."
        label.isEmpty() -> "2단계에서 전환할 앱을 선택하십시오."
        else -> null
    }

    private fun render() {
        val label = targetLabel()
        val running = MonitorState.running.value == true
        val detected = MonitorState.detected.value ?: ""
        val issue = problem(label)
        when {
            running && detected.isNotEmpty() -> {
                statusTitle.text = "등록된 사람 감지됨: $detected"
                statusHint.text = "'$label' 앱으로 전환했습니다."
            }
            running -> {
                statusTitle.text = "감시 중"
                statusHint.text = "등록된 사람이 보이면 '$label' 앱으로 전환합니다. " +
                    "다른 앱을 쓰는 동안에도 계속 감시합니다."
            }
            issue != null -> {
                statusTitle.text = "설정이 필요합니다"
                statusHint.text = issue
            }
            else -> {
                statusTitle.text = "감시 준비 완료"
                statusHint.text = "[감시 시작]을 누르면 등록된 ${Store.people.size}명을 감시합니다."
            }
        }
        toggle.setText(if (running) R.string.stop else R.string.start)
        toggle.isEnabled = running || issue == null
        targetName.text = label.ifEmpty { getString(R.string.no_target) }
        testSwitch.isEnabled = label.isNotEmpty()
        renderPeople()
    }

    private fun renderPeople() {
        peopleList.removeAllViews()
        if (Store.people.isEmpty()) {
            peopleList.addView(TextView(this).apply { setText(R.string.no_people) })
            return
        }
        for (person in Store.people) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            row.addView(
                TextView(this).apply {
                    text = "${person.name} (사진 ${person.vectors.size}장)"
                    textSize = 16f
                },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            )
            row.addView(
                MaterialButton(
                    this, null, androidx.appcompat.R.attr.borderlessButtonStyle
                ).apply {
                    setText(R.string.delete)
                    setOnClickListener { confirmRemove(person.name) }
                }
            )
            peopleList.addView(row)
        }
    }

    private fun confirmRemove(name: String) {
        MaterialAlertDialogBuilder(this)
            .setMessage("'$name'을(를) 목록에서 삭제하시겠습니까?")
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.delete) { _, _ ->
                Store.remove(this, name)
                if (Store.people.isEmpty()) stop()
                render()
            }
            .show()
    }

    // ---- 감지할 사람 등록 ----

    private fun withCamera(action: () -> Unit) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            action()
        } else {
            afterCamera = action
            askCamera.launch(Manifest.permission.CAMERA)
        }
    }

    private fun capture() {
        if (MonitorState.running.value == true) {
            toast("감시를 중지한 뒤 촬영하십시오.")
            return
        }
        val dir = File(cacheDir, "capture").apply { mkdirs() }
        val uri = FileProvider.getUriForFile(this, "$packageName.files", File(dir, "face.jpg"))
        captureUri = uri
        try {
            takePhoto.launch(uri)
        } catch (e: Exception) {
            toast("카메라 앱을 열 수 없습니다.")
        }
    }

    private fun registerFrom(uris: List<Uri>) {
        toast("얼굴을 찾는 중입니다...")
        worker.execute {
            val vectors = ArrayList<FloatArray>()
            var error: String? = null
            try {
                val current = engine ?: FaceEngine(applicationContext).also { engine = it }
                for (uri in uris) {
                    current.largestFace(this, uri)?.let { vectors.add(it) }
                }
            } catch (e: Throwable) {
                error = e.message ?: e.toString()
            }
            runOnUiThread {
                when {
                    isFinishing || isDestroyed -> Unit
                    error != null -> toast("사진을 처리하지 못했습니다: $error")
                    vectors.isEmpty() -> toast("사진에서 얼굴을 찾지 못했습니다.")
                    else -> askName(vectors, uris.size)
                }
            }
        }
    }

    private fun askName(vectors: List<FloatArray>, photoCount: Int) {
        val input = EditText(this).apply {
            hint = "이름"
            inputType = InputType.TYPE_CLASS_TEXT
            setSingleLine()
        }
        val margin = (20 * resources.displayMetrics.density).toInt()
        val container = FrameLayout(this).apply {
            addView(
                input,
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT
                ).apply { setMargins(margin, 0, margin, 0) }
            )
        }
        val message = if (vectors.size < photoCount) {
            "사진 ${photoCount}장 중 ${vectors.size}장에서 얼굴을 찾았습니다."
        } else {
            "얼굴 ${vectors.size}개를 찾았습니다."
        }
        MaterialAlertDialogBuilder(this)
            .setTitle("등록할 사람의 이름")
            .setMessage(message)
            .setView(container)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton("등록") { _, _ ->
                val name = input.text.toString().trim()
                if (name.isEmpty()) {
                    toast("이름을 입력해야 등록됩니다.")
                } else {
                    Store.add(this, name, vectors)
                    render()
                }
            }
            .show()
    }

    // ---- 전환할 앱 ----

    private fun chooseApp() {
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = packageManager.queryIntentActivities(launcher, 0)
            .map { it.activityInfo.packageName to it.loadLabel(packageManager).toString() }
            .filter { it.first != packageName }
            .distinctBy { it.first }
            .sortedBy { it.second.lowercase() }
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.choose_app)
            .setItems(apps.map { it.second }.toTypedArray()) { _, index ->
                Store.setTargetPackage(this, apps[index].first)
                render()
            }
            .show()
    }

    // ---- 감시 시작과 중지 ----

    private fun start() {
        if (problem(targetLabel()) != null) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            withCamera { start() }
            return
        }
        if (!Settings.canDrawOverlays(this)) {
            MaterialAlertDialogBuilder(this)
                .setTitle("권한이 필요합니다")
                .setMessage(
                    "다른 앱을 쓰는 중에 앱을 전환하려면 '다른 앱 위에 표시' 권한이 필요합니다. " +
                        "다음 화면에서 MolCom을 허용한 뒤 돌아와 [감시 시작]을 다시 누르십시오."
                )
                .setNegativeButton(android.R.string.cancel, null)
                .setPositiveButton("설정 열기") { _, _ ->
                    startActivity(
                        Intent(
                            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            Uri.parse("package:$packageName")
                        )
                    )
                }
                .show()
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !askedNotifications &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            // 알림은 거부해도 감시는 동작하므로 한 번만 묻는다.
            askedNotifications = true
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        ContextCompat.startForegroundService(this, Intent(this, MonitorService::class.java))
    }

    private fun stop() {
        if (MonitorState.running.value == true) {
            stopService(Intent(this, MonitorService::class.java))
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
