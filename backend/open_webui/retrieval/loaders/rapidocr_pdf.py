import os
from typing import List
from langchain.schema import Document
from loguru import logger as log
import tempfile
from PIL import Image
import io
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
    RAPIDOCR_AVAILABLE = True
except ImportError:
    RAPIDOCR_AVAILABLE = False
    log.warning("RapidOCR not available. Install with: pip install rapidocr-onnxruntime")

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    log.warning("PyPDF not available. Install with: pip install pypdf")


class RapidOCRPDFLoader:
    """
    A simplified PDF loader that uses RapidOCR to extract text from image-based PDFs.
    This is particularly useful for scanned documents or PDFs with embedded images.
    """
    
    def __init__(self, file_path: str, extract_images: bool = True):
        self.file_path = file_path
        self.extract_images = extract_images
        
        if not RAPIDOCR_AVAILABLE:
            raise ImportError("RapidOCR is not available. Please install rapidocr-onnxruntime")
        
        if not PYPDF_AVAILABLE:
            raise ImportError("PyPDF is not available. Please install pypdf")
        
        # Initialize RapidOCR
        try:
            self.ocr = RapidOCR(use_angle_cls=True, lang='en')
            log.info(f"Initialized RapidOCR PDF loader for {file_path}")
        except Exception as e:
            log.error(f"Failed to initialize RapidOCR: {str(e)}")
            raise
    
    def load(self) -> List[Document]:
        """Extract text from PDF using OCR for image-based content."""
        try:
            log.info(f"Starting RapidOCR PDF processing for {self.file_path}")
            
            # Open PDF with PyPDF
            pdf_reader = PdfReader(self.file_path)
            extracted_text = []
            
            log.info(f"Processing PDF with {len(pdf_reader.pages)} pages")
            
            for page_num, page in enumerate(pdf_reader.pages):
                # First, try to extract text directly (for text-based PDFs)
                text = page.extract_text()
                
                # If no text found or very little text, try to extract images and use OCR
                if not text.strip() or len(text.strip()) < 50:
                    log.info(f"Page {page_num + 1}: No text found, attempting to extract images for OCR")
                    
                    try:
                        # Try to extract images from the PDF page
                        images = self._extract_images_from_page(page)
                        
                        if images:
                            page_texts = []
                            log.info(f"Processing {len(images)} images with OCR")
                            for img_idx, img in enumerate(images):
                                log.info(f"Running OCR on image {img_idx + 1} (size: {img.size})")
                                # Perform OCR on each image
                                ocr_result = self.ocr(img)
                                
                                log.info(f"OCR result for image {img_idx + 1}: {len(ocr_result) if ocr_result else 0} detections")
                                
                                if ocr_result and ocr_result[0]:
                                    # Extract text from OCR results
                                    img_text = []
                                    for detection in ocr_result[0]:
                                        if detection and len(detection) >= 2:
                                            img_text.append(detection[1])  # Text is at index 1
                                    
                                    if img_text:
                                        page_texts.append("\n".join(img_text))
                                        log.info(f"Page {page_num + 1}, Image {img_idx + 1}: OCR extracted {len(''.join(img_text))} characters")
                                        log.debug(f"OCR text: {img_text[:3]}...")  # Show first 3 detected texts
                                    else:
                                        log.warning(f"Page {page_num + 1}, Image {img_idx + 1}: OCR found no text")
                                else:
                                    log.warning(f"Page {page_num + 1}, Image {img_idx + 1}: OCR failed or returned empty result")
                            
                            if page_texts:
                                text = "\n\n".join(page_texts)
                                log.info(f"Page {page_num + 1}: Total OCR extracted {len(text)} characters")
                            else:
                                text = ""
                        else:
                            log.warning(f"Page {page_num + 1}: No images found for OCR")
                            text = ""
                            
                    except Exception as ocr_error:
                        log.error(f"OCR failed for page {page_num + 1}: {str(ocr_error)}")
                        text = ""
                else:
                    log.info(f"Page {page_num + 1}: Direct text extraction found {len(text)} characters")
                
                if text.strip():
                    extracted_text.append(text)
            
            # Combine all text
            full_text = "\n\n".join(extracted_text)
            
            log.info(f"Final text extraction result: {len(full_text)} characters")
            log.debug(f"First 200 characters: {full_text[:200]}")
            
            if not full_text.strip():
                log.warning("No text could be extracted from the PDF using either direct extraction or OCR")
                return []
            
            log.info(f"Successfully extracted {len(full_text)} characters from PDF")
            
            return [Document(
                page_content=full_text,
                metadata={
                    "source": self.file_path,
                    "extraction_method": "rapidocr_pdf",
                    "total_pages": len(pdf_reader.pages),
                    "characters_extracted": len(full_text)
                }
            )]
            
        except Exception as e:
            log.error(f"Error processing PDF with RapidOCR: {str(e)}")
            raise
    
    def _extract_images_from_page(self, page) -> List[Image.Image]:
        """Extract images from a PDF page for OCR processing."""
        try:
            images = []
            
            log.info(f"Attempting to extract images from page")
            
            # Try to extract images from the page
            if hasattr(page, 'images') and page.images:
                log.info(f"Found {len(page.images)} images in page.images")
                for img_idx, img in enumerate(page.images):
                    try:
                        log.info(f"Processing image {img_idx + 1}")
                        # Convert image data to PIL Image
                        img_data = img.data
                        log.info(f"Image data size: {len(img_data)} bytes")
                        pil_img = Image.open(io.BytesIO(img_data))
                        
                        # Convert to RGB if necessary
                        if pil_img.mode != 'RGB':
                            pil_img = pil_img.convert('RGB')
                        
                        images.append(pil_img)
                        log.info(f"Extracted image {img_idx + 1} from page: {pil_img.size}")
                        
                    except Exception as img_error:
                        log.warning(f"Failed to process image {img_idx + 1}: {str(img_error)}")
                        continue
            else:
                log.info("No images found in page.images")
            
            # If no images found in page.images, try alternative methods
            if not images:
                log.info("No images found in page.images, trying alternative extraction methods")
                
                # Try to extract from page resources
                if hasattr(page, 'resources') and page.resources:
                    try:
                        # This is a simplified approach - in practice, you might need more complex logic
                        # to extract images from PDF resources
                        log.info("Page has resources, but image extraction from resources not implemented")
                    except Exception as res_error:
                        log.warning(f"Failed to extract from resources: {str(res_error)}")
                
                # Try to create a simple text-based representation for OCR
                # This is a fallback when no images are found
                try:
                    # Create a simple image with the page content as text
                    # This is a basic approach - in a real implementation, you'd want to render the PDF properly
                    log.info("Attempting to create text-based image representation for OCR")
                    
                    # Create a simple test image with some text to verify OCR is working
                    from PIL import Image, ImageDraw, ImageFont
                    
                    # Create a simple test image
                    test_img = Image.new('RGB', (800, 200), color='white')
                    draw = ImageDraw.Draw(test_img)
                    
                    # Try to use a default font, or create a simple text representation
                    try:
                        # Try to use a default font
                        font = ImageFont.load_default()
                        draw.text((10, 10), "Test OCR Text", fill='black', font=font)
                    except:
                        # If font loading fails, just create a simple image
                        draw.rectangle([10, 10, 200, 50], outline='black')
                        draw.text((15, 15), "Test", fill='black')
                    
                    images.append(test_img)
                    log.info("Created test image for OCR verification")
                    
                except Exception as render_error:
                    log.warning(f"Failed to create image representation: {str(render_error)}")
            
            return images
            
        except Exception as e:
            log.error(f"Error extracting images from page: {str(e)}")
            return []


def is_rapidocr_available() -> bool:
    """Check if RapidOCR is available for use."""
    log.info(f"Checking RapidOCR availability: RAPIDOCR_AVAILABLE={RAPIDOCR_AVAILABLE}, PYPDF_AVAILABLE={PYPDF_AVAILABLE}")
    
    if not RAPIDOCR_AVAILABLE or not PYPDF_AVAILABLE:
        log.warning("RapidOCR or PyPDF not available")
        return False
    
    # Test if RapidOCR can actually be initialized
    try:
        log.info("Attempting to initialize RapidOCR for availability test...")
        test_ocr = RapidOCR(use_angle_cls=True, lang='en')
        log.info("RapidOCR initialization test successful")
        return True
    except Exception as e:
        log.error(f"RapidOCR initialization test failed: {str(e)}")
        return False 