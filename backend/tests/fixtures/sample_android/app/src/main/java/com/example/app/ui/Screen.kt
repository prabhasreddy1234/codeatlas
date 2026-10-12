package com.example.app.ui

import androidx.compose.runtime.Composable

@Composable
fun UserScreen(viewModel: UserViewModel) {
    viewModel.refresh()
}
