export interface NavUser {
  name: string;
  email: string;
  avatarUrl?: string;
}

export interface NavBarProps {
  user?: NavUser;
  onAboutUs: () => void;
  onReports: () => void;
  onSignIn: () => void;
  onSignOut: () => void;
}
