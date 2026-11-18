package io.github.tuuuniSnowfield.erinnerungen

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.tuuuniSnowfield.erinnerungen.ui.ErinnerungenTheme
import io.github.tuuuniSnowfield.erinnerungen.ui.DetailScreen
import io.github.tuuuniSnowfield.erinnerungen.ui.HomeScreen
import io.github.tuuuniSnowfield.erinnerungen.ui.SettingsScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as ReminderApp
        setContent {
            ErinnerungenTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val nav = rememberNavController()
                    NavHost(navController = nav, startDestination = "home") {
                        composable("home") {
                            HomeScreen(app, nav)
                        }
                        composable("task/{uid}") { back ->
                            DetailScreen(app, nav, back.arguments?.getString("uid") ?: "")
                        }
                        composable("settings") {
                            SettingsScreen(app, nav)
                        }
                    }
                }
            }
        }
    }
}
