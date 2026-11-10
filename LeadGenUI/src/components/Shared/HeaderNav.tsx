"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/send-email", label: "Send Emails" },
  { href: "/settings", label: "Settings" },
];

interface HeaderNavProps {
  crawlerOnline?: boolean;
  stats?: { total_crawls?: number } | null;
}

export default function HeaderNav({ crawlerOnline, stats }: HeaderNavProps) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 bg-charcoal text-linen">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-12 gap-4">
          <div className="flex items-center gap-2.5">
            <Link href="/" className="flex items-baseline gap-1.5">
              <h1 className="text-base font-semibold leading-none tracking-tight text-linen">Flare</h1>
              <span className="text-base font-normal leading-none text-linen/60">crawler</span>
            </Link>

            {/* Navigation */}
            <nav className="ml-6 flex items-center gap-1">
              {NAV_ITEMS.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                      active
                        ? "bg-linen/15 text-linen"
                        : "text-linen/65 hover:text-linen hover:bg-linen/10"
                    )}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          {/* Crawler Status */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <div
                className={cn(
                  "w-1.5 h-1.5 rounded-full",
                  crawlerOnline ? "bg-sage" : "bg-ember"
                )}
              />
              <span className="text-xs text-linen/65">
                {crawlerOnline ? "Online" : "Offline"}
              </span>
            </div>
            {stats && (
              <Badge variant="secondary" className="text-xs h-5 px-1.5 bg-linen/15 text-linen border-0">
                {stats.total_crawls} crawls
              </Badge>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
