import { mediaFileUrl, type MediaFile } from '../../api'
import { Modal } from '../../components/Modal'

export function Lightbox({ system, file, onClose }: { system: string; file: MediaFile; onClose: () => void }) {
  return (
    <Modal title={`${file.folder} / ${file.filename}`} onClose={onClose} wide>
      <div className="lightbox checker">
        <img src={mediaFileUrl(system, file)} alt={file.filename} />
      </div>
    </Modal>
  )
}
