package com.example.app.other

class Item(val id: Int)

class ItemHolder(private val item: Item) {
    fun id(): Int = item.id
}
