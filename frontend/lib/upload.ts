import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/errors";
import { uploadContentType } from "@/lib/format";
import { t } from "@/lib/i18n";

type Ticket = { version_id: string; upload_url: string; content_type: string };

/**
 * Upload one file: get a signed URL from the API, send the file straight to storage,
 * then tell the API the upload is complete. Returns an error message, or null.
 */
export async function uploadFile(
  file: File,
  target: { matterId: string } | { documentId: string },
): Promise<string | null> {
  const body = {
    filename: file.name,
    content_type: uploadContentType(file),
    size_bytes: file.size,
  };
  const { data: ticket, error } =
    "matterId" in target
      ? await api.POST("/api/matters/{matter_id}/documents", {
          params: { path: { matter_id: target.matterId } },
          body,
        })
      : await api.POST("/api/documents/{document_id}/versions", {
          params: { path: { document_id: target.documentId } },
          body,
        });
  if (!ticket) return errorMessage(error);
  return sendAndComplete(file, ticket);
}

async function sendAndComplete(file: File, ticket: Ticket): Promise<string | null> {
  try {
    const put = await fetch(ticket.upload_url, {
      method: "PUT",
      body: file,
      headers: { "Content-Type": ticket.content_type },
    });
    if (!put.ok) return t.errors.upload_failed;
  } catch {
    return t.errors.upload_failed;
  }
  const { error } = await api.POST("/api/document-versions/{version_id}/complete", {
    params: { path: { version_id: ticket.version_id } },
  });
  return error ? errorMessage(error) : null;
}
