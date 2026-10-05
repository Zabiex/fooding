'use client'
import React from 'react'
const UsersButton = () => {
  return (
    <button className="bg-blue-500 text-white px-4 py-2 rounded" onClick={() => window.location.href = "/dashboard/users"}>
      Back to Users
    </button> 
    )
}
export default UsersButton