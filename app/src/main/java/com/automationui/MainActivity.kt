package com.automationui

import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RadioButtonChecked
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { Dashboard() }
    }

    @Composable
    private fun Dashboard() {
        var recording by remember { mutableStateOf(WorkflowStore.isRecording(this)) }
        var status by remember { mutableStateOf(WorkflowStore.status(this)) }
        var actions by remember { mutableStateOf(WorkflowStore.actions(this).toList()) }
        var replayLogs by remember { mutableStateOf(WorkflowStore.replayLogs(this)) }
        var recordText by remember { mutableStateOf(WorkflowStore.isRecordingText(this)) }
        var waitTarget by remember { mutableStateOf("") }
        var waitTimeoutSeconds by remember { mutableStateOf("15") }
        var waitBeforeAction by remember { mutableStateOf("") }

        val exportLauncher = rememberLauncherForActivityResult(
            ActivityResultContracts.CreateDocument("application/json")
        ) { uri ->
            if (uri != null) {
                runCatching {
                    val payload = WorkflowStore.exportJson(this@MainActivity)
                    contentResolver.openOutputStream(uri)?.use { stream ->
                        stream.write(payload.toByteArray(Charsets.UTF_8))
                    } ?: throw IllegalStateException("Could not open the selected export destination.")
                }.onSuccess {
                    WorkflowStore.setStatus(this@MainActivity, "Workflow JSON exported")
                    status = WorkflowStore.status(this@MainActivity)
                }.onFailure { error ->
                    WorkflowStore.setStatus(this@MainActivity, "Export failed: ${error.message ?: "unknown error"}")
                    status = WorkflowStore.status(this@MainActivity)
                }
            }
        }

        val importLauncher = rememberLauncherForActivityResult(
            ActivityResultContracts.OpenDocument()
        ) { uri ->
            if (uri != null) {
                runCatching {
                    val payload = contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
                        ?: throw IllegalStateException("Could not read the selected JSON file.")
                    WorkflowStore.importJson(this@MainActivity, payload, merge = true)
                }.onSuccess { added ->
                    actions = WorkflowStore.actions(this@MainActivity).toList()
                    WorkflowStore.setStatus(this@MainActivity, "Imported/merged workflow; ${added} new actions added")
                    status = WorkflowStore.status(this@MainActivity)
                }.onFailure { error ->
                    WorkflowStore.setStatus(this@MainActivity, "Import failed: ${error.message ?: "invalid JSON"}")
                    status = WorkflowStore.status(this@MainActivity)
                }
            }
        }

        LaunchedEffect(Unit) {
            while (true) {
                recording = WorkflowStore.isRecording(this@MainActivity)
                status = WorkflowStore.status(this@MainActivity)
                actions = WorkflowStore.actions(this@MainActivity).toList()
                replayLogs = WorkflowStore.replayLogs(this@MainActivity)
                recordText = WorkflowStore.isRecordingText(this@MainActivity)
                delay(500)
            }
        }

        MaterialTheme {
            Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text("Automation UI", style = MaterialTheme.typography.headlineMedium)
                    Text("Record supported UI actions and replay them on this Android device.")

                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                        Column(
                            Modifier.fillMaxWidth().padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text("Status", style = MaterialTheme.typography.labelLarge)
                            Text(status, style = MaterialTheme.typography.bodyLarge)
                            Text("${actions.size} recorded actions", style = MaterialTheme.typography.bodyMedium)
                        }
                    }

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                if (!WorkflowStore.isRecording(this@MainActivity)) {
                                    WorkflowStore.clear(this@MainActivity)
                                    WorkflowStore.setRecording(this@MainActivity, true)
                                    WorkflowStore.setStatus(this@MainActivity, "Recording… leave this app and perform your steps")
                                } else {
                                    WorkflowStore.setRecording(this@MainActivity, false)
                                    WorkflowStore.setStatus(this@MainActivity, "Recording stopped and saved locally")
                                }
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            androidx.compose.material3.Icon(
                                if (recording) Icons.Default.Stop else Icons.Default.RadioButtonChecked,
                                contentDescription = null
                            )
                            Spacer(Modifier.height(1.dp))
                            Text(if (recording) "Stop" else "Record")
                        }
                        Button(
                            onClick = {
                                WorkflowStore.clearReplayLog(this@MainActivity)
                                sendBroadcast(Intent(AutomationAccessibilityService.ACTION_REPLAY).setPackage(packageName))
                                WorkflowStore.setStatus(this@MainActivity, "Replay requested")
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            androidx.compose.material3.Icon(Icons.Default.PlayArrow, contentDescription = null)
                            Text("Replay")
                        }
                    }

                    OutlinedButton(
                        onClick = {
                            sendBroadcast(Intent(AutomationAccessibilityService.ACTION_STOP).setPackage(packageName))
                            WorkflowStore.setRecording(this@MainActivity, false)
                            WorkflowStore.setStatus(this@MainActivity, "Stop requested")
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Stop replay immediately") }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = recordText,
                            onCheckedChange = {
                                WorkflowStore.setRecordingText(this@MainActivity, it)
                                recordText = it
                            }
                        )
                        Column(Modifier.weight(1f)) {
                            Text("Record text input (optional)", style = MaterialTheme.typography.bodyMedium)
                            Text(
                                "Off by default. Password fields are never recorded.",
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                    }

                    OutlinedButton(
                        onClick = {
                            if (WorkflowStore.isRecording(this@MainActivity)) {
                                WorkflowStore.addAction(
                                    this@MainActivity,
                                    RecordedAction(
                                        type = "OPEN_SETTINGS",
                                        packageName = "com.android.settings",
                                        text = null,
                                        viewId = null,
                                        contentDescription = null,
                                        className = null,
                                        left = 0,
                                        top = 0,
                                        right = 0,
                                        bottom = 0,
                                        screenWidth = resources.displayMetrics.widthPixels,
                                        screenHeight = resources.displayMetrics.heightPixels,
                                        scrollDeltaY = 0,
                                        timestamp = System.currentTimeMillis()
                                    )
                                )
                                WorkflowStore.setStatus(
                                    this@MainActivity,
                                    "Recorded OPEN_SETTINGS; opening Android Settings"
                                )
                            }
                            startActivity(Intent(Settings.ACTION_SETTINGS))
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Open Android Settings (record this step)") }

                    OutlinedButton(
                        onClick = { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Enable Accessibility Service") }

                    OutlinedButton(
                        onClick = {
                            WorkflowStore.clear(this@MainActivity)
                            WorkflowStore.clearReplayLog(this@MainActivity)
                            actions = emptyList()
                            replayLogs = emptyList()
                            WorkflowStore.setStatus(this@MainActivity, "Workflow cleared")
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Clear workflow") }

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = { exportLauncher.launch("automation-workflow.json") },
                            modifier = Modifier.weight(1f)
                        ) { Text("Export JSON") }
                        OutlinedButton(
                            onClick = { importLauncher.launch(arrayOf("application/json", "text/plain", "*/*")) },
                            modifier = Modifier.weight(1f)
                        ) { Text("Import / merge JSON") }
                    }
                    Text(
                        "Import ADB gesture JSON here. Taps and scrolls already captured by Accessibility are deduplicated.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    Divider()
                    Text("Wait for UI condition", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Add a checkpoint before an action. Replay waits until this text is visible; if it times out, replay stops instead of blindly continuing.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    OutlinedTextField(
                        value = waitTarget,
                        onValueChange = { waitTarget = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Visible text or button label") },
                        singleLine = true
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = waitBeforeAction,
                            onValueChange = { waitBeforeAction = it.filter(Char::isDigit).take(3) },
                            modifier = Modifier.weight(1f),
                            label = { Text("Before action #") },
                            singleLine = true,
                            placeholder = { Text("Last action") }
                        )
                        OutlinedTextField(
                            value = waitTimeoutSeconds,
                            onValueChange = { waitTimeoutSeconds = it.filter(Char::isDigit).take(3) },
                            modifier = Modifier.weight(1f),
                            label = { Text("Timeout (seconds)") },
                            singleLine = true
                        )
                    }
                    OutlinedButton(
                        onClick = {
                            val target = waitTarget.trim()
                            val timeoutSeconds = waitTimeoutSeconds.toLongOrNull()?.coerceIn(1L, 120L) ?: 15L
                            val current = WorkflowStore.actions(this@MainActivity)
                            if (target.isBlank()) {
                                WorkflowStore.setStatus(this@MainActivity, "Enter the text to wait for")
                            } else {
                                val waitAction = RecordedAction(
                                    type = "WAIT_FOR_UI",
                                    packageName = null,
                                    text = target,
                                    viewId = null,
                                    contentDescription = null,
                                    className = null,
                                    left = 0, top = 0, right = 0, bottom = 0,
                                    screenWidth = resources.displayMetrics.widthPixels,
                                    screenHeight = resources.displayMetrics.heightPixels,
                                    scrollDeltaY = 0,
                                    timestamp = System.currentTimeMillis(),
                                    waitTimeoutMs = timeoutSeconds * 1000L
                                )
                                val oneBasedPosition = waitBeforeAction.toIntOrNull()
                                    ?.coerceIn(1, current.size.coerceAtLeast(1))
                                    ?: current.size.coerceAtLeast(1)
                                WorkflowStore.insertActionAt(this@MainActivity, waitAction, oneBasedPosition - 1)
                                actions = WorkflowStore.actions(this@MainActivity).toList()
                                waitTarget = ""
                                waitBeforeAction = ""
                                WorkflowStore.setStatus(
                                    this@MainActivity,
                                    "Inserted UI wait before action #$oneBasedPosition"
                                )
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = !recording
                    ) { Text(if (recording) "Stop recording before adding UI wait" else "Insert UI wait before action") }

                    Divider()
                    Text("Replay diagnostics", style = MaterialTheme.typography.titleMedium)
                    if (replayLogs.isEmpty()) {
                        Text(
                            "Run Replay to see which actions succeeded or were skipped.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        replayLogs.takeLast(4).asReversed().forEach { line ->
                            Text(
                                line,
                                style = MaterialTheme.typography.bodySmall,
                                maxLines = 2
                            )
                        }
                    }
                    Divider()
                    Text("Recorded actions", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "This app records actions Android exposes to Accessibility. It cannot capture every raw touch or every protected system screen.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        actions.forEachIndexed { index, action ->
                            Card {
                                Column(Modifier.fillMaxWidth().padding(12.dp)) {
                                    Text("${index + 1}. ${action.type}", style = MaterialTheme.typography.titleSmall)
                                    Text(action.packageName ?: "System action", style = MaterialTheme.typography.bodySmall)
                                    if (!action.text.isNullOrBlank()) Text(action.text, style = MaterialTheme.typography.bodyMedium)
                                    if (!action.viewId.isNullOrBlank()) Text(action.viewId, style = MaterialTheme.typography.labelSmall)
                                    if (action.type == "GESTURE") {
                                        Text(
                                            "${action.gestureKind ?: "UNKNOWN"} · ${action.gestureDurationMs} ms",
                                            style = MaterialTheme.typography.labelSmall
                                        )
                                    }
                                    if (action.type == "WAIT") {
                                        Text(
                                            "Recorded pause · ${action.waitDurationMs / 1000.0}s",
                                            style = MaterialTheme.typography.labelSmall
                                        )
                                    }
                                    if (action.type == "WAIT_FOR_UI") {
                                        Text(
                                            "Wait for visible text · timeout ${action.waitTimeoutMs / 1000}s",
                                            style = MaterialTheme.typography.labelSmall
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
