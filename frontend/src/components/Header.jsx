import { LogIn, LogOut } from "lucide-react";

export default function Header({ user, loading, onConnect, onLogout }) {
  return (
    <header className="sticky top-0 z-20 border-b-2 border-ink bg-bg">
      <div className="mx-auto grid max-w-[1500px] gap-3 px-4 py-4 lg:grid-cols-[1fr_auto] lg:px-6">
        <div>
          <p className="font-display text-7xl leading-none tracking-normal">TRACKSIEVE</p>
          <p className="text-xs uppercase text-muted">Spotify duplicate removal desk</p>
        </div>

        <div className="flex items-center gap-3 justify-self-start lg:justify-self-end">
          {user?.images?.[0]?.url && <img className="h-12 w-12 border-2 border-ink object-cover" src={user.images[0].url} alt="" />}
          <div className="text-right text-xs uppercase">
            <p className="font-bold">{user?.display_name || (loading ? "Checking access" : "Not connected")}</p>
            <button className="icon-button mt-1" onClick={user ? onLogout : onConnect}>
              {user ? <LogOut size={18} /> : <LogIn size={18} />}
              {user ? "Disconnect" : "Connect Spotify"}
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
