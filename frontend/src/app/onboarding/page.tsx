"use client";

import { useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useAuth, getHomeRoute } from "@/lib/auth";
import { markOnboardingSeen } from "@/lib/storage";
import { TOUR_SLIDES } from "@/lib/onboarding-tour-content";
import { TierXLogo } from "@/components/tierx-logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function OnboardingPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [index, setIndex] = useState(0);

  const slide = TOUR_SLIDES[index];
  const isLastSlide = index === TOUR_SLIDES.length - 1;
  const features = slide.features ?? [];
  const capabilities = slide.capabilities ?? [];

  function dismiss() {
    markOnboardingSeen();
    router.replace(user ? getHomeRoute(user) : "/login");
  }

  return (
    <div className="dark brand-dark min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto w-full max-w-[1320px] px-6 py-12">
        <div className="flex items-center justify-center gap-4">
          <TierXLogo className="size-12 text-primary" />
          <span className="text-4xl font-bold tracking-tight">TierX</span>
        </div>

        <h1 className="mt-8 text-center text-5xl font-bold">
          {slide.headline}
        </h1>
        <p className="mx-auto mt-6 max-w-[700px] text-center text-xl text-muted-foreground">
          {slide.subheadline}
        </p>

        {slide.placeholderNote ? (
          <div className="mt-16 flex min-h-[320px] items-center justify-center rounded-lg border border-dashed border-[#404040] px-8 py-16">
            <p className="max-w-[560px] text-center text-base text-muted-foreground">
              {slide.placeholderNote}
            </p>
          </div>
        ) : null}

        {features.length > 0 ? (
          <div className="mt-16 grid gap-8 md:grid-cols-2 lg:grid-cols-3">
            {features.map(({ icon: Icon, image, title, body }) => (
              <article
                key={title}
                className="flex flex-col items-center rounded-lg bg-card px-8 py-8 text-center"
              >
                <div className="flex size-20 items-center justify-center rounded-full bg-primary/20">
                  <Icon className="size-8 text-primary" strokeWidth={1.75} />
                </div>
                <div className="relative mt-6 h-40 w-full max-w-[280px] overflow-hidden rounded-md bg-[#999999]/10">
                  <Image
                    src={image}
                    alt=""
                    fill
                    sizes="(min-width: 1024px) 280px, 90vw"
                    className="object-contain p-2"
                  />
                </div>
                <h2 className="mt-6 text-xl font-bold">{title}</h2>
                <p className="mt-4 text-sm text-muted-foreground">{body}</p>
              </article>
            ))}
          </div>
        ) : null}

        {capabilities.length > 0 ? (
          <div className="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {capabilities.map(
              ({ icon: Icon, iconClassName, title, detail }) => (
                <div
                  key={title}
                  className="flex flex-col items-center rounded-lg border border-[#404040] bg-card/50 px-6 py-6 text-center"
                >
                  <Icon className={cn("size-7", iconClassName)} />
                  <p className="mt-4 text-base font-bold">{title}</p>
                  <p className="mt-2 text-xs text-[#737373]">{detail}</p>
                </div>
              ),
            )}
          </div>
        ) : null}

        <div className="mt-16 flex flex-wrap items-center justify-center gap-4">
          {index > 0 ? (
            <Button
              variant="secondary"
              onClick={() => setIndex(index - 1)}
              className="h-[60px] w-[228px] rounded-md text-lg"
            >
              Zurück
            </Button>
          ) : null}
          <Button
            onClick={() => (isLastSlide ? dismiss() : setIndex(index + 1))}
            className="h-[60px] w-[230px] rounded-md text-lg"
          >
            {isLastSlide ? "Dashboard starten" : "Weiter"}
          </Button>
          <Button
            variant="secondary"
            onClick={dismiss}
            className="h-[60px] w-[228px] rounded-md text-lg"
          >
            Tour überspringen
          </Button>
        </div>

        {/* Padded buttons keep a comfortable hit target around the small dot. */}
        <div className="mt-10 flex items-center justify-center">
          {TOUR_SLIDES.map((tourSlide, dot) => (
            <button
              key={tourSlide.id}
              type="button"
              onClick={() => setIndex(dot)}
              aria-label={`Zu Schritt ${dot + 1} von ${TOUR_SLIDES.length}`}
              aria-current={dot === index ? "true" : undefined}
              className="group flex size-11 items-center justify-center rounded-full"
            >
              <span
                className={cn(
                  "size-4 rounded-full transition-colors",
                  dot === index
                    ? "bg-primary"
                    : "bg-[#525252] group-hover:bg-[#737373]",
                )}
              />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
