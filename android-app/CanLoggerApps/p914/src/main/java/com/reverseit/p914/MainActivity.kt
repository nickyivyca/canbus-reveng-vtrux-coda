package com.reverseit.p914

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat

/**
 * Settings and bring-up for the 914 logger. Reached from the cog on [DisplayActivity], which is
 * now the launcher; the content is unchanged from when this was the only screen.
 *
 * Deliberately plain: a link-health readout, the transport buttons, firmware flashing and the
 * root OTG toggle. Same arrangement as `:coda` and `:vtrux`, where the live display is the face
 * of the app and the old bring-up screen becomes settings behind a cog.
 *
 * Built in code rather than from a layout resource, because a single status readout and a few
 * buttons do not justify a layout file that would then need maintaining alongside the real UI.
 */
class MainActivity : ComponentActivity() {

    private lateinit var status: TextView
    private lateinit var otgResult: TextView
    private val handler = Handler(Looper.getMainLooper())
    private val app get() = application as P914Application

    private val requestNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            Log.i("P914", "POST_NOTIFICATIONS granted: $granted")
        }

    private val tick = object : Runnable {
        override fun run() {
            status.text = app.statusLine()
            handler.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Keep the screen on while this activity is in front.
        //
        // Two reasons. During bring-up the phone is the only readout, and a sleeping screen
        // ends the session. In the car this is a dash display, so it should never sleep anyway.
        //
        // This is distinct from the PARTIAL_WAKE_LOCK CanLoggingService takes while logging:
        // that keeps the CPU alive so USB bulk transfers keep being serviced (and stops Android
        // enabling USB autosuspend, which detaches the device), but it deliberately does not
        // keep the screen on. The two cover different failure modes and both are wanted.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Android 13+ discards the foreground-service notification silently if this is not
        // granted at the moment startForeground() runs, and never shows it again.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
            setBackgroundColor(Color.BLACK)
        }

        root.addView(TextView(this).apply {
            text = "914 logger"
            setTextColor(Color.WHITE)
            textSize = 22f
            typeface = Typeface.DEFAULT_BOLD
        })

        root.addView(TextView(this).apply {
            text = "SLCAN over TCP ${P914Constants.BRIDGE_HOST}:${P914Constants.BRIDGE_PORT}\n" +
                "adb reverse tcp:${P914Constants.BRIDGE_PORT} tcp:${P914Constants.BRIDGE_PORT}"
            setTextColor(Color.GRAY)
            textSize = 12f
            setPadding(0, 8, 0, 24)
        })

        status = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            setTextColor(Color.GREEN)
            textSize = 14f
            text = "idle"
        }
        root.addView(status, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(Button(this).apply {
            text = "USB (car)"
            setOnClickListener { app.connect(P914Application.Transport.USB) }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(Button(this).apply {
            text = "TCP (replay)"
            setOnClickListener { app.connect(P914Application.Transport.TCP) }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(Button(this).apply {
            text = "Stop"
            setOnClickListener { app.disconnect() }
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.gravity = Gravity.CENTER
        root.addView(row)

        root.addView(Button(this).apply {
            text = "Flash firmware..."
            setOnClickListener { startActivity(Intent(this@MainActivity, FlashActivity::class.java)) }
        })

        // Forces USB host mode via root. The first press is what makes the app appear in
        // Magisk's superuser list at all -- an app only shows up once it has actually called su.
        root.addView(Button(this).apply {
            text = "Force USB host (root)"
            setOnClickListener {
                otgResult.text = "requesting root..."
                Thread {
                    val r = RootOtg.forceHost()
                    runOnUiThread {
                        otgResult.text = buildString {
                            appendLine("rc=${r.exitCode}  mode=${r.modeAfter}  role=${r.roleAfter}")
                            appendLine(if (r.isHost) "HOST MODE ACTIVE" else "NOT host -- see output")
                            appendLine(r.output)
                        }
                    }
                }.apply { isDaemon = true }.start()
            }
        })

        otgResult = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            setTextColor(Color.YELLOW)
            textSize = 10f
            text = ""
        }
        root.addView(otgResult, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        setContentView(root)

        handleLaunchIntent(intent)
    }

    override fun onNewIntent(newIntent: Intent) {
        super.onNewIntent(newIntent)
        setIntent(newIntent)
        handleLaunchIntent(newIntent)
    }

    /**
     * Connect if the launch asked for it.
     *
     * `--ez autoconnect true` drives a bring-up run from adb without simulating taps. The
     * `USB_DEVICE_ATTACHED` half moved to [DisplayActivity] along with the manifest filter: a
     * plugged-in VCU should raise the display, not this screen, and the filter has to sit on the
     * activity Android actually launches for the persistent permission grant to be offered.
     */
    private fun handleLaunchIntent(i: Intent?) {
        if (i?.getBooleanExtra("autoconnect", false) == true) {
            status.text = "autoconnect requested"
            app.connect(P914Application.Transport.USB)
        }
    }

    override fun onStart() {
        super.onStart()
        handler.post(tick)
    }

    override fun onStop() {
        super.onStop()
        handler.removeCallbacks(tick)
    }
}
