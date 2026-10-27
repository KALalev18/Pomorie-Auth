import { useState, useRef, useEffect, type KeyboardEvent } from 'react';
import type { NavBarProps } from './NavBar.types';

/* ─────────────────────────── helpers ─────────────────────────── */

function UserAvatar({ name, avatarUrl }: { name: string; avatarUrl?: string }) {
  const initials = name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        className="h-8 w-8 rounded-full object-cover ring-2 ring-white/30"
      />
    );
  }

  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-500 text-xs font-semibold text-white ring-2 ring-white/30 select-none">
      {initials}
    </span>
  );
}

/* ─────────────────────────── icons ──────────────────────────── */

function MapPinIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
    </svg>
  );
}

function BellIcon({ hasUnread = false }: { hasUnread?: boolean }) {
  return (
    <span className="relative">
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0" />
      </svg>
      {hasUnread && (
        <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-red-400 ring-1 ring-white/20" />
      )}
    </span>
  );
}

function InfoIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg className="h-3.5 w-3.5 opacity-60" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

/* ─────────────────────────── component ──────────────────────── */

export default function NavBar({ user, onAboutUs, onReports, onSignIn, onSignOut }: NavBarProps) {
  const [profileOpen, setProfileOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  /* close dropdown when clicking outside */
  useEffect(() => {
    function handleOutsideClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    }
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  function handleDropdownKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === 'Escape') setProfileOpen(false);
  }

  return (
    <header className="absolute inset-x-0 top-0 z-30">
      {/* frosted glass bar */}
      <nav className="mx-3 mt-3 flex items-center justify-between rounded-2xl border border-white/15 bg-slate-900/75 px-4 py-2.5 shadow-lg backdrop-blur-md">

        {/* ── left: logo ── */}
        <div className="flex items-center gap-2 select-none">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-indigo-500 text-white shadow-inner">
            <MapPinIcon />
          </span>
          <span className="text-sm font-bold tracking-tight text-white">
            Pomorie<span className="font-light opacity-70">Reports</span>
          </span>
        </div>

        {/* ── center: nav links ── */}
        <div className="hidden items-center gap-1 sm:flex">
          <NavLink onClick={onReports}>
            <MapPinIcon />
            Доклади
          </NavLink>
          <NavLink onClick={onAboutUs}>
            <InfoIcon />
            За нас
          </NavLink>
        </div>

        {/* ── right: actions + profile ── */}
        <div className="flex items-center gap-1">
          {/* notifications – only when signed in */}
          {user && (
            <IconButton label="Известия" onClick={() => {}}>
              <BellIcon hasUnread />
            </IconButton>
          )}

          {/* about us – icon for small screens */}
          <span className="sm:hidden">
            <IconButton label="За нас" onClick={onAboutUs}>
              <InfoIcon />
            </IconButton>
          </span>

          {/* profile or sign-in */}
          {user ? (
            <div className="relative" ref={dropdownRef}>
              <button
                aria-haspopup="true"
                aria-expanded={profileOpen}
                onClick={() => setProfileOpen((v) => !v)}
                onKeyDown={handleDropdownKey}
                className="flex cursor-pointer items-center gap-2 rounded-xl px-2 py-1 text-white/90 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
              >
                <UserAvatar name={user.name} avatarUrl={user.avatarUrl} />
                <span className="hidden text-xs font-medium sm:block">{user.name}</span>
                <ChevronDownIcon />
              </button>

              {profileOpen && (
                <div className="animate-fade-in absolute right-0 mt-2 w-52 rounded-2xl border border-white/20 bg-slate-900/80 p-1 shadow-2xl backdrop-blur-xl">
                  <div className="border-b border-white/10 px-3 py-2">
                    <p className="text-xs font-semibold text-white">{user.name}</p>
                    <p className="mt-0.5 truncate text-[11px] text-white/50">{user.email}</p>
                  </div>
                  <DropdownItem onClick={() => { setProfileOpen(false); }}>
                    Моят профил
                  </DropdownItem>
                  <DropdownItem onClick={() => { setProfileOpen(false); }}>
                    Настройки
                  </DropdownItem>
                  <DropdownItem onClick={() => { setProfileOpen(false); }}>
                    Моите доклади
                  </DropdownItem>
                  <div className="mt-1 border-t border-white/10 pt-1">
                    <DropdownItem danger onClick={() => { setProfileOpen(false); onSignOut(); }}>
                      Изход
                    </DropdownItem>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={onSignIn}
              className="rounded-xl bg-white/15 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
            >
              Вход
            </button>
          )}
        </div>
      </nav>
    </header>
  );
}

/* ─────────────────────────── sub-components ─────────────────── */

function NavLink({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium text-white/80 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
    >
      {children}
    </button>
  );
}

function IconButton({ children, label, onClick }: { children: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className="flex cursor-pointer items-center justify-center rounded-xl p-2 text-white/70 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
    >
      {children}
    </button>
  );
}

function DropdownItem({ children, danger = false, onClick }: { children: React.ReactNode; danger?: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full cursor-pointer rounded-xl px-3 py-2 text-left text-xs font-medium transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40 ${
        danger ? 'text-red-400 hover:bg-red-500/10' : 'text-white/80 hover:text-white'
      }`}
    >
      {children}
    </button>
  );
}
