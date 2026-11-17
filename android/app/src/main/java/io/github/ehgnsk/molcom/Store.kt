package io.github.ehgnsk.molcom

import android.content.Context
import androidx.lifecycle.MutableLiveData
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class Person(val name: String, val vectors: List<FloatArray>)

/** 감시 서비스의 상태. 화면이 이 값을 지켜본다. */
object MonitorState {
    val running = MutableLiveData(false)
    val detected = MutableLiveData("")
    val error = MutableLiveData("")
}

/** 블랙리스트와 설정. 사진은 보관하지 않고 얼굴 특징 벡터만 저장한다. */
object Store {
    private const val PREFS = "molcom"
    private const val FILE = "blacklist.json"

    // OpenCV가 SFace 모델에 권장하는 코사인 유사도 기준은 0.363이다.
    private val thresholds = mapOf("low" to 0.45f, "normal" to 0.363f, "high" to 0.30f)

    @Volatile
    var people: List<Person> = emptyList()
        private set

    @Volatile
    var threshold = 0.363f
        private set

    private var loaded = false

    @Synchronized
    fun load(context: Context) {
        if (loaded) return
        loaded = true
        threshold = thresholds[sensitivity(context)] ?: 0.363f
        val file = File(context.filesDir, FILE)
        if (!file.exists()) return
        try {
            val array = JSONArray(file.readText())
            val list = ArrayList<Person>()
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                val vectors = item.getJSONArray("embeddings")
                val parsed = ArrayList<FloatArray>()
                for (j in 0 until vectors.length()) {
                    val values = vectors.getJSONArray(j)
                    parsed.add(FloatArray(values.length()) { values.getDouble(it).toFloat() })
                }
                if (parsed.isNotEmpty()) list.add(Person(item.getString("name"), parsed))
            }
            people = list
        } catch (e: Exception) {
            people = emptyList()
        }
    }

    private fun save(context: Context) {
        val array = JSONArray()
        for (person in people) {
            val vectors = JSONArray()
            for (vector in person.vectors) {
                val values = JSONArray()
                for (value in vector) values.put(value.toDouble())
                vectors.put(values)
            }
            array.put(JSONObject().put("name", person.name).put("embeddings", vectors))
        }
        File(context.filesDir, FILE).writeText(array.toString())
    }

    /** 인물을 등록한다. 같은 이름이 있으면 그 사람에게 사진을 추가한다. */
    @Synchronized
    fun add(context: Context, name: String, vectors: List<FloatArray>) {
        val list = people.toMutableList()
        val index = list.indexOfFirst { it.name == name }
        if (index >= 0) {
            list[index] = Person(name, list[index].vectors + vectors)
        } else {
            list.add(Person(name, vectors))
        }
        people = list
        save(context)
    }

    @Synchronized
    fun remove(context: Context, name: String) {
        people = people.filter { it.name != name }
        save(context)
    }

    /** 가장 비슷한 등록 인물의 이름. 기준에 못 미치면 null. */
    fun match(vector: FloatArray): String? {
        var bestName: String? = null
        var bestScore = threshold
        for (person in people) {
            for (known in person.vectors) {
                if (known.size != vector.size) continue
                var score = 0f
                for (i in vector.indices) score += known[i] * vector[i]
                if (score >= bestScore) {
                    bestScore = score
                    bestName = person.name
                }
            }
        }
        return bestName
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun targetPackage(context: Context): String =
        prefs(context).getString("target", "") ?: ""

    fun setTargetPackage(context: Context, value: String) {
        prefs(context).edit().putString("target", value).apply()
    }

    fun sensitivity(context: Context): String =
        prefs(context).getString("sensitivity", "normal") ?: "normal"

    fun setSensitivity(context: Context, value: String) {
        prefs(context).edit().putString("sensitivity", value).apply()
        threshold = thresholds[value] ?: 0.363f
    }
}
