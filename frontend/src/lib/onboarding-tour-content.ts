import type { ComponentType } from "react";
import {
  Bell,
  ChartLine,
  File,
  Lock,
  Radar,
  Users,
  type LucideIcon,
} from "lucide-react";

import { CloudIcon, type CustomIconProps } from "@/components/custom-icons";

export interface TourFeature {
  icon: LucideIcon;
  image: string;
  title: string;
  body: string;
}

export interface TourCapability {
  icon: ComponentType<CustomIconProps>;
  iconClassName: string;
  title: string;
  detail: string;
}

export interface TourSlide {
  id: string;
  headline: string;
  subheadline: string;
  /** Absent while a slide is still a placeholder — the page renders a stub. */
  features?: TourFeature[];
  capabilities?: TourCapability[];
  /** Shown in place of the content grids on placeholder slides. */
  placeholderNote?: string;
}

const FEATURES: TourFeature[] = [
  {
    icon: Radar,
    image: "/onboarding/threat-detection.png",
    title: "Echtzeit-Bedrohungserkennung",
    body: "Identifizieren Sie Sicherheitsbedrohungen sofort mit unserer KI-gestützten Analyse-Engine, die rund um die Uhr Ihr Netzwerk überwacht.",
  },
  {
    icon: ChartLine,
    image: "/onboarding/analytics.png",
    title: "Intelligente Analysen",
    body: "Erhalten Sie detaillierte Einblicke durch fortschrittliche Datenvisualisierung und maschinelles Lernen für präzise Sicherheitsbewertungen.",
  },
  {
    icon: Bell,
    image: "/onboarding/automated-alerts.png",
    title: "Automatisierte Alarme",
    body: "Konfigurieren Sie benutzerdefinierte Benachrichtigungen und automatisierte Reaktionen auf Sicherheitsvorfälle nach Ihren Anforderungen.",
  },
];

const CAPABILITIES: TourCapability[] = [
  {
    icon: Lock,
    iconClassName: "text-[#22c55e] [&>rect]:fill-current",
    title: "Verschlüsselung",
    detail: "Ende-zu-Ende gesichert",
  },
  {
    icon: CloudIcon,
    iconClassName: "text-primary",
    title: "Cloud-Integration",
    detail: "AWS, Azure, GCP",
  },
  {
    icon: Users,
    iconClassName: "text-[#f59e0b] fill-current",
    title: "Team-Zusammenarbeit",
    detail: "Unbegrenzte Benutzer",
  },
  {
    icon: File,
    iconClassName: "text-[#a855f7]",
    title: "Compliance-Reports",
    detail: "GDPR, ISO 27001",
  },
];

export const TOUR_SLIDES: TourSlide[] = [
  {
    id: "welcome",
    headline: "Willkommen bei TierX Dashboard",
    subheadline:
      "Ihr intelligentes Security Operations Center für umfassende Bedrohungserkennung und -analyse",
    features: FEATURES,
    capabilities: CAPABILITIES,
  },
  {
    id: "setup",
    headline: "Einrichtung",
    subheadline: "Dieser Schritt der Tour wird gerade erstellt.",
    placeholderNote:
      "Platzhalter – hier folgen die Inhalte zur Einrichtung von Mandant, Alert-Typen und Schema.",
  },
  {
    id: "workflows",
    headline: "Analyse und Workflows",
    subheadline: "Dieser Schritt der Tour wird gerade erstellt.",
    placeholderNote:
      "Platzhalter – hier folgen die Inhalte zu Alerts, Clustern und Playbooks.",
  },
];
