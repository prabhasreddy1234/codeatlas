package com.example.app.data

interface UserRepository {
    fun fetchUsers(): List<String>
}
