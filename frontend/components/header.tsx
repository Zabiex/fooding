import Image from 'next/image';
import Link from 'next/link';
import User from './user';
import Menu from './menu';


const links = [
    { href: '/log', label: 'Log', primary: false },
    { href: '/tracking', label: 'Tracking', primary: false },
    { href: '/planning', label: 'Planning', primary: false },
] as const;

const Header = () => {
    return (
        <header className="sticky top-0 z-50 border-b border-emerald-950/10 bg-[#E7EDDF]">
            <nav
                aria-label="Main navigation"
                className="mx-auto flex max-w-7xl items-center justify-between px-5 py-1"
            >
                <Link href="/" className="flex items-center gap-2 text-2xl font-bold tracking-tight text-emerald-950">
                    <Image
                        src="/sprout.png"
                        alt=""
                        width={40}
                        height={40}
                        className="h-10 w-10 object-contain"
                    />
                    
                </Link>
                <Menu />
                {/*
                Current component called 'Navbar' has been renamed to 'Header'
                Removed 'Menu' component
                Added 'User' component as a dropdown menu for profile, settings, and logout instead 
                */}
                <User />
            </nav>
                
        </header>
    );
};

export default Header;