import Image from 'next/image';
import Link from 'next/link';

const links = [
    { href: '/profile', label: 'Profile', primary: false },
    { href: '/settings', label: 'Settings', primary: false },
    { href: '/logout', label: 'Logout', primary: false },
] as const;

type UserProps = {
    name?: string;
    imageUrl?: string;
};

const User = ({ name = 'Guest User', imageUrl }: UserProps) => {
    const initials = name
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0])
        .join('')
        .toUpperCase() || 'U';

    return (
        <details className="group relative shrink-0">
            <summary
                aria-label={`Open account menu for ${name}`}
                className="flex h-10 w-10 cursor-pointer list-none items-center justify-center overflow-hidden rounded-full bg-[#A3B69B] text-sm font-semibold text-emerald-950 ring-2 ring-green-900/10 transition hover:ring-green-900/30 [&::-webkit-details-marker]:hidden"
            >
                {imageUrl ? (
                    <Image
                        src={imageUrl}
                        alt=""
                        width={40}
                        height={40}
                        className="h-full w-full object-cover"
                    />
                ) : (
                    initials
                )}
            </summary>
            <div className="absolute right-0 top-12 z-10 flex min-w-48 flex-col rounded-md border border-green-950/10 bg-[#fffdf7] p-2 shadow-lg">
                <p className="border-b border-green-950/10 px-3 py-2 text-sm font-semibold text-emerald-950">
                    {name}
                </p>
                {links.map((link) => (
                    <Link
                        key={link.href}
                        href={link.href}
                        className="rounded px-3 py-2 text-sm text-green-950 hover:bg-emerald-950/5"
                    >
                        {link.label}
                    </Link>
                ))}
            </div>
        </details>
    );
};

export default User