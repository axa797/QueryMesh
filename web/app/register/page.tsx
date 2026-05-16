import { redirect } from "next/navigation";

/** Legacy `/register` — password signup removed; OAuth sign-in lives on `/login`. */
export default function RegisterRedirect() {
  redirect("/login");
}
