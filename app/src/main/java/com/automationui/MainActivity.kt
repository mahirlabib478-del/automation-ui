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
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { Dashboard() }
    }

    @Composable
    private fun Dashboard() {
        var recording by remember { mutableStateOf(WorkflowStore.isRecording(this)) }
        var status by remember { mutableStateOf(WorkflowStore.status(this)) }
        var actions by remember { mutableStateOf(WorkflowStore.actions(this)) }

        MaterialTheme {
            Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Text("Automation UI", style = MaterialTheme.typography.headlineMedium)
                    Text("Record actions. Replay supported UI interactions on this device.")
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("Status", style = MaterialTheme.typography.labelLarge)
                            Text(status, style = MaterialTheme.typography.bodyLarge)
                            Text("${actions.size} events saved", style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                if (!recording) {
                                    WorkflowStore.clear(this@MainActivity)
                                    WorkflowStore.setRecording(this@MainActivity, true)
                                    status = "Recording accessibility-visible events"
                                } else {
                                    WorkflowStore.setRecording(this@MainActivity, false)
                                    status = "Recording stopped"
                                }
                                recording = !recording
                                actions = WorkflowStore.actions(this@MainActivity)
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            androidx.compose.material3.Icon(
                                if (recording) Icons.Default.Stop else Icons.Default.RadioButtonChecked,
                                contentDescription = null
                            )
                            Spacer(Modifier.padding(start = 4.dp))
                            Text(if (recording) "Stop" else "Record")
                        }
                        Button(
                            onClick = {
                                sendBroadcast(Intent(AutomationAccessibilityService.ACTION_REPLAY).setPackage(packageName))
                                status = "Replay requested"
                            },
                            modifier = Modifier.weight(1f)
                        ) {
                            androidx.compose.material3.Icon(Icons.Default.PlayArrow, contentDescription = null)
                            Spacer(Modifier.padding(start = 4.dp))
                            Text("Replay")
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
                            status = "Workflow cleared"
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Clear workflow") }

                    Divider()
                    Text("Recorded events", style = MaterialTheme.typography.titleMedium)
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        itemsIndexed(actions) { index, action ->
                            Card {
                                Column(Modifier.fillMaxWidth().padding(12.dp)) {
                                    Text("${index + 1}. ${action.type}", style = MaterialTheme.typography.titleSmall)
                                    Text(action.packageName ?: "Unknown app", style = MaterialTheme.typography.bodySmall)
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
