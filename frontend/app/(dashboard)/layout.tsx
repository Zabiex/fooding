import React from 'react'
const Layout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div>
        <p>Dashboard navbar</p>
        {children}
    </div>  
  )
}
export default Layout