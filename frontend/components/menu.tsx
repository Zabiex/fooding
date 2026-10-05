import Link from 'next/link';
import { CalendarDays, ChartNoAxesCombined, NotebookPen } from 'lucide-react';

const links = [
    { href: '/log', label: 'Log', icon: NotebookPen, primary: false },
    { href: '/tracking', label: 'Tracking', icon: ChartNoAxesCombined, primary: false },
    { href: '/planning', label: 'Planning', icon: CalendarDays, primary: false },
] as const;


const Menu = () => (
    <nav aria-label="Main menu" className="flex flex-1 items-center justify-center gap-4 md:gap-35 lg:gap-50 py-4 overflow-x-auto bg-[#E7EDDF]">
        {links.map((link) => {
            const Icon = link.icon;

            return (
                <Link
                    key={link.href}
                    href={link.href}
                    aria-label={link.label}
                    title={link.label}
                    className={`shrink-0 rounded-full border border-emerald-950/15 bg-[#3D674B] px-4 py-2 text-sm transition-colors hover:bg-emerald-950/5 ${link.primary ? 'font-semibold text-white-900' : 'font-medium text-white-950'}`}
                >
                    <Icon aria-hidden="true" size={18} />
                </Link>
            );
        })}
    </nav>
);

export default Menu;
