package com.example.app.ui

import androidx.lifecycle.ViewModel
import com.example.app.data.UserRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

@HiltViewModel
class UserViewModel @Inject constructor(
    private val repository: UserRepository
) : ViewModel() {

    fun refresh() {
        repository.fetchUsers()
        repository.nothingHere()
    }
}
