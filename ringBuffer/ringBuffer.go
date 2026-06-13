package ringBuffer

import(
	"sync"
)

type Sequenced interface {
    GetSeq() int
}

type RingBuffer[T Sequenced] struct{
	buffer []T
	size int
	count int
	write int
	mu sync.RWMutex
}

func NewRingBuffer[T Sequenced](size int) *RingBuffer[T]{
	return &RingBuffer[T]{
		buffer: make([]T, size),
		size: size,
	}
}

func (rb *RingBuffer[T]) Add(val T){
	rb.mu.Lock()
	defer rb.mu.Unlock()
	//we need to write at write
	rb.buffer[rb.write]=val
	rb.write = (rb.write+1)%rb.size
	if rb.count<rb.size{
		rb.count++;
	}
}

func (rb *RingBuffer[T]) Get()[]T{
	rb.mu.RLock()
	defer rb.mu.RUnlock()
	result:=make([]T,0,rb.count)
	for i:=0;i<rb.count;i++{
		ind:=(rb.write+rb.size-rb.count+i)%rb.size
		result=append(result,rb.buffer[ind])
	}
	return result
}

func (rb *RingBuffer[T]) Len()int{
	rb.mu.RLock()
	defer rb.mu.RUnlock()
	return rb.count
}

func (rb *RingBuffer[T]) Latest() (T, bool) {
    rb.mu.RLock()
    defer rb.mu.RUnlock()

    var zero T
    if rb.count == 0 {
        return zero, false
    }

    // write is already pointing to next slot, so latest is one behind
    idx := (rb.write - 1 + rb.size) % rb.size
    return rb.buffer[idx], true
}

func (rb *RingBuffer[T]) GetSince(seq int) []T {
    rb.mu.RLock()
    defer rb.mu.RUnlock()

    result := make([]T, 0)
    for i := 0; i < rb.count; i++ {
        idx := (rb.write + rb.size - rb.count + i) % rb.size
        if rb.buffer[idx].GetSeq() > seq {
            result = append(result, rb.buffer[idx])
        }
    }
    return result
}