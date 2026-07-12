import { Outlet, useLocation, useNavigate, useParams } from "react-router"
import { Badge } from "~/components/ui/badge"
import { BreadcrumbItem, BreadcrumbList, Breadcrumb, BreadcrumbSeparator } from "~/components/ui/breadcrumb"

export default function CorpusLayout() {
  const { id } = useParams()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const activeTab = pathname.endsWith("/view") ? "view" : "detail"

  return (
    <div className="flex w-full flex-col gap-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>Home</BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>Corpus</BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>{id}</BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-semibold">{id}</h2>
        <Badge>corpus</Badge>
      </div>

      <div className="flex items-center gap-2 border-b">
        <button
          onClick={() => navigate(`/corpus/${id}`)}
          className={`-mb-px border-b-2 px-2 py-1 text-sm ${
            activeTab === "detail" ? "border-neutral-900 font-medium dark:border-neutral-100" : "border-transparent text-neutral-500"
          }`}
        >
          Detail
        </button>
        <button
          onClick={() => navigate(`/corpus/${id}/view`)}
          className={`-mb-px border-b-2 px-2 py-1 text-sm ${
            activeTab === "view" ? "border-neutral-900 font-medium dark:border-neutral-100" : "border-transparent text-neutral-500"
          }`}
        >
          View
        </button>
      </div>

      <Outlet />
    </div>
  )
}
