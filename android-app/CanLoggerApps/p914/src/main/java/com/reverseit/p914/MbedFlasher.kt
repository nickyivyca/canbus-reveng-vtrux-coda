package com.reverseit.p914

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.documentfile.provider.DocumentFile
import java.io.InputStream
import java.security.MessageDigest

/**
 * Flashes the VCU by writing a `.bin` to the mbed interface MCU's mass-storage volume.
 *
 * The LPC1768's interface MCU exposes a small FAT volume; dropping a binary on it programs the
 * target. That is the same flash-by-copy route used from a laptop, so nothing here is novel to
 * Android -- what Android adds is that the volume arrives as a SAF tree rather than a drive letter.
 *
 * The app already claims the CDC interfaces of this device for SLCAN. Mass storage is a *separate*
 * interface (intf 0, left to the kernel's `usb-storage`), which is why both can be in use at once
 * and why the flash path needs no change to the serial path.
 *
 * ### Ordering matters, and it is not obvious
 *
 * Established the hard way from a laptop on 2026-08-13 and recorded in the project hub's
 * `notes/artifacts/README.md`: **the LPC1768 does not auto-reset after programming here**, and a
 * reset sent too early leaves the target halted with no serial output at all -- indistinguishable
 * from a bricked board until you send another reset. So the sequence is
 *
 *   1. delete the existing `.bin`, write the new one
 *   2. **wait for programming to finish** -- reading the file back proves the FAT write landed,
 *      not that the target was programmed, so the readback is a necessary check and an insufficient one
 *   3. *then* reset (a serial BREAK -- see [UsbCdcSerial.sendBreak])
 *
 * Step 3 is deliberately not done here. This object's job ends at "the bytes are on the volume";
 * the reset needs the CDC interface, so [P914Application] owns the whole sequence.
 *
 * ### The MBED.HTM guard
 *
 * [flash] refuses to write to a tree that has no `MBED.HTM` in it. A SAF tree URI is just a folder
 * the user picked, and the picker will happily offer internal storage or an unrelated USB stick;
 * without this check a mis-tap would scatter firmware into a random directory. `MBED.HTM` is the
 * mbed interface firmware's own signature file, so its presence is a positive identification of
 * the right volume rather than a guess from a name or a UUID.
 */
object MbedFlasher {

    private const val TAG = "P914"

    /** The mbed interface firmware's signature file. Its presence identifies the volume. */
    const val SIGNATURE_FILE = "MBED.HTM"

    /** Written by the interface MCU when it rejects an image. Absence is part of a good outcome. */
    private const val FAIL_FILE = "FAIL.TXT"

    /** LPC1768 flash. An image larger than this cannot be for this target. */
    private const val MAX_IMAGE_BYTES = 512 * 1024

    private const val COPY_BUFFER = 64 * 1024

    data class Result(
        val ok: Boolean,
        val message: String,
        /** MD5 of the bytes written, so it can be checked against the build host's. */
        val md5: String? = null,
        val bytes: Long = 0,
    )

    /** True if [treeUri] looks like the mbed volume. Cheap enough to call before showing UI. */
    fun isMbedVolume(context: Context, treeUri: Uri): Boolean = runCatching {
        val tree = DocumentFile.fromTreeUri(context, treeUri) ?: return false
        tree.findFile(SIGNATURE_FILE) != null
    }.getOrDefault(false)

    /**
     * Write [source] to the mbed volume as [name].
     *
     * Blocking, and can block for a long time -- or, if the MSD endpoint wedges, indefinitely.
     * That wedge is a real observed failure on this hardware (recorded in the hub notes; it hung a
     * laptop shell until the cable was replugged). There is no way to abort a blocked SAF call, so
     * the mitigation is structural: callers must run this off the main thread, which keeps the UI
     * responsive enough to show that it is stuck rather than freezing the app.
     *
     * [log] receives human-readable progress; it is called from this thread.
     */
    fun flash(
        context: Context,
        treeUri: Uri,
        source: InputStream,
        name: String,
        expectedBytes: Long,
        log: (String) -> Unit,
    ): Result {
        if (expectedBytes <= 0) {
            return Result(false, "image is empty")
        }
        if (expectedBytes > MAX_IMAGE_BYTES) {
            return Result(false, "image is ${expectedBytes} bytes, larger than the LPC1768's 512 KB flash")
        }

        val tree = DocumentFile.fromTreeUri(context, treeUri)
            ?: return Result(false, "cannot open the volume -- was the grant lost?")
        if (!tree.canWrite()) {
            return Result(false, "volume is not writable")
        }

        // Positive identification before anything destructive happens.
        val children = tree.listFiles()
        if (children.none { it.name.equals(SIGNATURE_FILE, ignoreCase = true) }) {
            return Result(false, "no $SIGNATURE_FILE here -- this is not the MBED volume, refusing to write")
        }
        log("volume confirmed ($SIGNATURE_FILE present)")

        // A FAIL.TXT left from a previous attempt would be mistaken for a report on this one.
        children.firstOrNull { it.name.equals(FAIL_FILE, ignoreCase = true) }?.let {
            log("clearing stale $FAIL_FILE from a previous attempt")
            it.delete()
        }

        // The interface MCU programs from the newest .bin; stale images also eat its small flash.
        children.filter { it.isFile && it.name?.endsWith(".bin", ignoreCase = true) == true }
            .forEach {
                log("removing existing ${it.name}")
                if (!it.delete()) return Result(false, "could not delete ${it.name}")
            }

        val target = tree.createFile("application/octet-stream", name)
            ?: return Result(false, "could not create $name on the volume")
        log("writing ${target.name} (${expectedBytes} bytes)")

        val digest = MessageDigest.getInstance("MD5")
        var written = 0L
        try {
            context.contentResolver.openOutputStream(target.uri, "wt").use { out ->
                if (out == null) return Result(false, "could not open $name for writing")
                val buf = ByteArray(COPY_BUFFER)
                while (true) {
                    val n = source.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    digest.update(buf, 0, n)
                    written += n
                }
                out.flush()
                // Push it to the device rather than leaving it in a page cache: the whole point is
                // that the interface MCU sees the bytes, and we are about to reset the target.
                (out as? java.io.FileOutputStream)?.fd?.sync()
            }
        } catch (e: Exception) {
            Log.e(TAG, "flash write failed", e)
            return Result(false, "write failed after $written bytes: ${e.message}")
        }

        val writtenMd5 = digest.digest().toHex()
        log("wrote $written bytes, md5 $writtenMd5")
        if (written != expectedBytes) {
            return Result(false, "short write: $written of $expectedBytes bytes", writtenMd5, written)
        }

        // Read back. This proves the FAT write landed and the volume is not silently discarding
        // data -- it says nothing about whether the target was programmed, which only the target
        // coming back on the serial link can show.
        log("reading back to verify...")
        val readMd5 = runCatching {
            val d = MessageDigest.getInstance("MD5")
            context.contentResolver.openInputStream(target.uri)!!.use { input ->
                val buf = ByteArray(COPY_BUFFER)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    d.update(buf, 0, n)
                }
            }
            d.digest().toHex()
        }.getOrElse { return Result(false, "readback failed: ${it.message}", writtenMd5, written) }

        if (readMd5 != writtenMd5) {
            return Result(false, "readback mismatch: wrote $writtenMd5, read $readMd5", writtenMd5, written)
        }
        log("readback matches")
        return Result(true, "image on volume, md5 $writtenMd5", writtenMd5, written)
    }

    /** Contents of `FAIL.TXT` if the interface MCU rejected the image, else null. */
    fun readFailure(context: Context, treeUri: Uri): String? = runCatching {
        val tree = DocumentFile.fromTreeUri(context, treeUri) ?: return null
        val fail = tree.findFile(FAIL_FILE) ?: return null
        context.contentResolver.openInputStream(fail.uri)?.use {
            it.readBytes().toString(Charsets.US_ASCII).trim()
        }
    }.getOrNull()

    private fun ByteArray.toHex(): String =
        joinToString("") { "%02x".format(it) }
}
