package com.reverseit.p914

import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.storage.StorageManager
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import java.io.File
import java.io.InputStream

/**
 * Flash a firmware image to the VCU from the phone.
 *
 * Why this exists: with the phone in the car and the laptop not, the VCU was previously
 * unflashable without carrying a laptop out to it. The mbed interface MCU's mass-storage volume is
 * an ordinary FAT volume that Android mounts on attach, so the phone can do what the laptop did --
 * which makes firmware and app development possible in the same sitting.
 *
 * ### This is a tool driven from adb, not a screen anyone uses
 *
 * The expected operator is an assistant session over wifi adb, not a person tapping buttons, so
 * the primary interface is the command line:
 *
 *     adb push fw.bin /sdcard/Android/data/com.reverseit.p914/files/Firmware/
 *     adb shell am start -n com.reverseit.p914/.FlashActivity -e image fw.bin --ez go true
 *     adb logcat -s P914
 *
 * Everything the screen shows also goes to logcat under `P914`, so a headless run is fully
 * observable without `uiautomator`.
 *
 * The UI is not decoration, though, and cannot be removed: **the one-time volume grant has to come
 * from the document picker**, and a SAF permission cannot be granted from a shell. So the screen
 * exists mainly to host that grant, with manual selection and a confirmation dialog as the
 * by-hand fallback.
 *
 * Its own activity, not part of [MainActivity], because this is a development tool and the main
 * screen becomes the in-car display. Nothing here should end up on the dash.
 *
 * ### Why it is exported, and what stops that being a hole
 *
 * `am start` from a shell cannot launch a non-exported component, so driving this from adb means
 * exporting it -- which in principle lets any installed app ask for a firmware flash. The guard is
 * that [imageFromExtra] resolves names **only** inside this app's own external files directory and
 * rejects anything that escapes it. An exported component that can only flash files another
 * process would already have had to place in our directory is not a meaningful escalation.
 */
class FlashActivity : ComponentActivity() {

    private companion object {
        const val TAG = "P914"
        const val PREFS = "p914"
        const val KEY_TREE = "mbed_tree_uri"
        const val FIRMWARE_DIR = "Firmware"

        /** `-e image <filename>` -- a name in the app's own `Firmware/` dir, not a path. */
        const val EXTRA_IMAGE = "image"

        /** `--ez go true` -- flash immediately, skipping the confirmation dialog. */
        const val EXTRA_GO = "go"
    }

    /** One selectable image, from either source. Reading is deferred so nothing is held in memory. */
    private class Image(val name: String, val size: Long, val open: () -> InputStream)

    private lateinit var volumeLine: TextView
    private lateinit var imageList: LinearLayout
    private lateinit var logView: TextView
    private lateinit var logScroll: ScrollView
    private lateinit var flashButton: Button

    private var treeUri: Uri? = null
    private var selected: Image? = null
    private var busy = false

    private val prefs by lazy { getSharedPreferences(PREFS, MODE_PRIVATE) }
    private val app get() = application as P914Application

    private val pickTree =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
            val uri = r.data?.data ?: return@registerForActivityResult
            // Persist it: without this the grant dies with the process and the volume has to be
            // re-picked on every launch.
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
            )
            if (!MbedFlasher.isMbedVolume(this, uri)) {
                log("that folder has no ${MbedFlasher.SIGNATURE_FILE} -- not the MBED volume")
                return@registerForActivityResult
            }
            treeUri = uri
            prefs.edit().putString(KEY_TREE, uri.toString()).apply()
            log("MBED volume granted")
            refresh()
        }

    private val pickFile =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri == null) return@registerForActivityResult
            var name = "firmware.bin"
            var size = 0L
            contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val si = c.getColumnIndex(OpenableColumns.SIZE)
                    if (ni >= 0) name = c.getString(ni)
                    if (si >= 0) size = c.getLong(si)
                }
            }
            selected = Image(name, size) { contentResolver.openInputStream(uri)!! }
            log("selected $name ($size bytes)")
            refresh()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        prefs.getString(KEY_TREE, null)?.let { saved ->
            val uri = Uri.parse(saved)
            // A persisted grant can outlive the volume -- the drive may simply not be plugged in.
            // Checking now means the UI says so instead of failing at the moment of writing.
            if (contentResolver.persistedUriPermissions.any { it.uri == uri && it.isWritePermission }) {
                treeUri = uri
            }
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
            setBackgroundColor(Color.BLACK)
        }

        root.addView(TextView(this).apply {
            text = "Flash VCU firmware"
            setTextColor(Color.WHITE)
            textSize = 22f
            typeface = Typeface.DEFAULT_BOLD
        })

        volumeLine = TextView(this).apply {
            setTextColor(Color.GRAY)
            textSize = 12f
            setPadding(0, 8, 0, 8)
        }
        root.addView(volumeLine)

        root.addView(Button(this).apply {
            text = "Pick MBED volume"
            setOnClickListener { launchTreePicker() }
        })

        root.addView(TextView(this).apply {
            text = "Image"
            setTextColor(Color.WHITE)
            textSize = 14f
            typeface = Typeface.DEFAULT_BOLD
            setPadding(0, 24, 0, 4)
        })
        root.addView(TextView(this).apply {
            text = "adb push fw.bin /sdcard/Android/data/$packageName/files/$FIRMWARE_DIR/"
            setTextColor(Color.GRAY)
            textSize = 10f
            typeface = Typeface.MONOSPACE
            setPadding(0, 0, 0, 8)
        })

        imageList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(imageList)

        root.addView(Button(this).apply {
            text = "Browse..."
            setOnClickListener { pickFile.launch(arrayOf("*/*")) }
        })

        flashButton = Button(this).apply {
            text = "FLASH + RESET"
            setOnClickListener { confirmAndFlash() }
        }
        root.addView(flashButton, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = 24 })

        logView = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            setTextColor(Color.GREEN)
            textSize = 11f
        }
        logScroll = ScrollView(this).apply { addView(logView) }
        root.addView(logScroll, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        root.addView(Button(this).apply {
            text = "Back"
            setOnClickListener { finish() }
        }, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { gravity = Gravity.CENTER })

        setContentView(root)
        refresh()
        handleIntentExtras(intent)
    }

    override fun onNewIntent(newIntent: Intent) {
        super.onNewIntent(newIntent)
        setIntent(newIntent)
        refresh()
        handleIntentExtras(newIntent)
    }

    /**
     * Apply `-e image <name>` and `--ez go true` from an adb launch.
     *
     * The extras are stripped once acted on, so a relaunch of an existing task -- or anything else
     * that redelivers the intent -- cannot re-flash the car off a stale command.
     */
    private fun handleIntentExtras(i: Intent?) {
        if (i == null) return
        val name = i.getStringExtra(EXTRA_IMAGE)
        val go = i.getBooleanExtra(EXTRA_GO, false)
        i.removeExtra(EXTRA_IMAGE)
        i.removeExtra(EXTRA_GO)

        if (name != null) {
            val img = imageFromExtra(name)
            if (img == null) {
                log("no such image in $FIRMWARE_DIR/: $name")
                return
            }
            selected = img
            log("selected ${img.name} (${img.size} bytes)")
            refresh()
        }
        if (!go) return

        val img = selected
        val tree = treeUri
        when {
            img == null -> log("--ez go given with no image selected")
            tree == null -> log("--ez go given but the MBED volume has not been granted -- " +
                "tap 'Pick MBED volume' once; a SAF grant cannot come from a shell")
            else -> startFlash(tree, img)
        }
    }

    /**
     * Resolve an intent-supplied name against the app's `Firmware/` dir.
     *
     * Rejects anything whose canonical path escapes that directory, which is what makes exporting
     * this activity safe: a caller supplies a name, never a path, and cannot reach a file it did
     * not already put where only this app can write.
     */
    private fun imageFromExtra(name: String): Image? {
        val dir = firmwareDir()
        val f = File(dir, name)
        if (!f.canonicalPath.startsWith(dir.canonicalPath + File.separator)) {
            log("rejected '$name': outside $FIRMWARE_DIR/")
            return null
        }
        if (!f.isFile) return null
        return Image(f.name, f.length()) { f.inputStream() }
    }

    /**
     * On API 29+ the picker can be pointed straight at the removable volume, which matters because
     * finding it by hand in the document picker is genuinely fiddly. Below that, and if no
     * removable volume is mounted, fall back to the plain picker.
     */
    private fun launchTreePicker() {
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val sm = getSystemService(StorageManager::class.java)
            sm?.storageVolumes
                ?.firstOrNull { it.isRemovable && it.state == android.os.Environment.MEDIA_MOUNTED }
                ?.createOpenDocumentTreeIntent()
        } else null
        pickTree.launch(
            (intent ?: Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)).apply {
                addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
            }
        )
    }

    private fun firmwareDir(): File =
        File(getExternalFilesDir(null), FIRMWARE_DIR).also { it.mkdirs() }

    private fun refresh() {
        volumeLine.text = when {
            treeUri == null -> "MBED volume: not selected"
            !MbedFlasher.isMbedVolume(this, treeUri!!) ->
                "MBED volume: granted, but not reachable (VCU unplugged?)"
            else -> "MBED volume: ready"
        }

        imageList.removeAllViews()
        val files = firmwareDir().listFiles { f -> f.isFile && f.name.endsWith(".bin", true) }
            ?.sortedBy { it.name } ?: emptyList()
        if (files.isEmpty()) {
            imageList.addView(TextView(this).apply {
                text = "(no .bin in ${FIRMWARE_DIR}/ -- push one, or Browse)"
                setTextColor(Color.GRAY)
                textSize = 11f
            })
        }
        for (f in files) {
            val isSel = selected?.name == f.name && selected?.size == f.length()
            imageList.addView(Button(this).apply {
                text = "${if (isSel) "> " else ""}${f.name}  (${f.length()} B)"
                setOnClickListener {
                    selected = Image(f.name, f.length()) { f.inputStream() }
                    log("selected ${f.name} (${f.length()} bytes)")
                    refresh()
                }
            })
        }

        flashButton.isEnabled = !busy && treeUri != null && selected != null
        flashButton.text = when {
            busy -> "WORKING..."
            selected == null -> "FLASH + RESET (pick an image)"
            treeUri == null -> "FLASH + RESET (pick the volume)"
            else -> "FLASH ${selected!!.name} + RESET"
        }
    }

    /**
     * Reflashing a running vehicle is not something to do on a stray tap, and the button sits next
     * to the image list it acts on. The dialog names the image and its size so a wrong selection
     * is visible before it is written, not after.
     */
    private fun confirmAndFlash() {
        val img = selected ?: return
        val tree = treeUri ?: return
        AlertDialog.Builder(this)
            .setTitle("Flash the VCU?")
            .setMessage(
                "${img.name}\n${img.size} bytes\n\n" +
                    "This overwrites the firmware on the car and resets it. Logging stops and " +
                    "restarts."
            )
            .setPositiveButton("Flash") { _, _ -> startFlash(tree, img) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startFlash(tree: Uri, img: Image) {
        busy = true
        refresh()
        logView.text = ""
        log("=== flashing ${img.name} ===")
        Thread {
            val ok = runCatching {
                app.flashAndReset(tree, img.open, img.name, img.size) { log(it) }
            }.getOrElse { log("unexpected failure: ${it.message}"); false }
            runOnUiThread {
                busy = false
                log(if (ok) "=== done ===" else "=== did not complete ===")
                refresh()
            }
        }.apply { isDaemon = true; name = "mbed-flash" }.start()
    }

    /**
     * Everything visible on screen also goes to logcat, because the screen is the secondary
     * channel here -- a run driven from adb has to be fully readable from `logcat -s P914`.
     */
    private fun log(line: String) {
        android.util.Log.i(TAG, line)
        runOnUiThread {
            logView.append(if (logView.text.isEmpty()) line else "\n$line")
            logScroll.post { logScroll.fullScroll(ScrollView.FOCUS_DOWN) }
        }
    }
}
