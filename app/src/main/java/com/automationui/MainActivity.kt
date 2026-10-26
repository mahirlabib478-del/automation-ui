package com.automationui

import android.content.Intent
import android.os.Bundle
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
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
        var recordText by remember { mutableStateOf(WorkflowStore.isRecordingText(this)) }

        LaunchedEffect(Unit) {
            while (true) {
                recording = WorkflowStore.isRecording(this@MainActivity)
                status = WorkflowStore.status(this@MainActivity)
                actions = WorkflowStore.actions(this@MainActivity).toList()
                recordText = WorkflowStore.isRecordingText(this@MainActivity)
                delay(500)
            }
        }

        MaterialTheme {
            Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(20.dp),
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
                        onClick = { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Enable Accessibility Service") }

                    OutlinedButton(
                        onClick = {
                            WorkflowStore.clear(this@MainActivity)
                            actions = emptyList()
                            WorkflowStore.setStatus(this@MainActivity, "Workflow cleared")
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Clear workflow") }

                    Divider()
                    Text("Recorded actions", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "This app records actions Android exposes to Accessibility. It cannot capture every raw touch or every protected system screen.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        itemsIndexed(actions) { index, action ->
                            Card {
                                Column(Modifier.fillMaxWidth().padding(12.dp)) {
                                    Text("${index + 1}. ${action.type}", style = MaterialTheme.typography.titleSmall)
                                    Text(action.packageName ?: "System action", style = MaterialTheme.typography.bodySmall)
                                    if (!action.text.isNullOrBlank()) Text(action.text, style = MaterialTheme.typography.bodyMedium)
                                    if (!action.viewId.isNullOrBlank()) Text(action.viewId, style = MaterialTheme.typography.labelSmall)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
