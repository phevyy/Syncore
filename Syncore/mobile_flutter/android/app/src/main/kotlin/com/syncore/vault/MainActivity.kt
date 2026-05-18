package com.syncore.vault

import android.app.ActivityManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        @Suppress("DEPRECATION")
        setTaskDescription(ActivityManager.TaskDescription("Syncore"))
    }
}
