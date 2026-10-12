package com.example.app.data

import javax.inject.Inject

class UserRepositoryImpl @Inject constructor(
    private val dao: UserDao,
    private val api: ApiService
) : UserRepository {

    override fun fetchUsers(): List<String> {
        api.get()
        return dao.all()
    }
}
