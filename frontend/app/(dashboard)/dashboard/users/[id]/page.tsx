import UsersButton from '@/components/users-button'
import React from 'react'
const UserDetails = async({ params }: { params: Promise<{ id: string }> }) => {
  const { id } = await params
  return (
    <div>
        <h1>Showing details for user {id}</h1>
        <UsersButton />
      </div>
  )
}
export default UserDetails